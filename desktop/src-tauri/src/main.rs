#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use rand::RngCore;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::process::Command;
use std::thread;
use std::time::{Duration, Instant};

const DESKTOP_AUTH_BRIDGE_URL: &str =
    "https://klgaby440-lang.github.io/l-link-crypt/app/";

fn open_system_browser(url: &str) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        let command = format!("start \"\" \"{}\"", url.replace('"', ""));
        Command::new("cmd")
            .args(["/C", command.as_str()])
            .spawn()
            .map_err(|error| format!("Impossible d'ouvrir le navigateur système : {error}"))?;
    }
    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .arg(url)
            .spawn()
            .map_err(|error| format!("Impossible d'ouvrir le navigateur système : {error}"))?;
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        Command::new("xdg-open")
            .arg(url)
            .spawn()
            .map_err(|error| format!("Impossible d'ouvrir le navigateur système : {error}"))?;
    }
    Ok(())
}

fn find_header_end(buffer: &[u8]) -> Option<usize> {
    buffer.windows(4).position(|window| window == b"\r\n\r\n")
}

fn decode_form_component(value: &str) -> Result<String, String> {
    let bytes = value.as_bytes();
    let mut decoded = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        match bytes[index] {
            b'+' => {
                decoded.push(b' ');
                index += 1;
            }
            b'%' if index + 2 < bytes.len() => {
                let hex = std::str::from_utf8(&bytes[index + 1..index + 3])
                    .map_err(|_| "Encodage du formulaire invalide".to_string())?;
                let byte = u8::from_str_radix(hex, 16)
                    .map_err(|_| "Encodage du formulaire invalide".to_string())?;
                decoded.push(byte);
                index += 3;
            }
            byte => {
                decoded.push(byte);
                index += 1;
            }
        }
    }
    String::from_utf8(decoded).map_err(|_| "Formulaire UTF-8 invalide".to_string())
}

fn form_value(body: &str, key: &str) -> Option<String> {
    body.split('&').find_map(|part| {
        let (raw_key, raw_value) = part.split_once('=')?;
        let decoded_key = decode_form_component(raw_key).ok()?;
        if decoded_key == key {
            decode_form_component(raw_value).ok()
        } else {
            None
        }
    })
}

fn respond(stream: &mut TcpStream, status: &str, message: &str) {
    let body = format!(
        "<!doctype html><html lang=\"fr\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\"><title>Llink</title><body style=\"font-family:system-ui;padding:40px;max-width:560px;margin:auto\"><h2>{}</h2><p>{}</p><p>Tu peux fermer cet onglet et revenir dans Llink.</p></body></html>",
        if status.starts_with("200") { "Connexion terminée" } else { "Connexion non terminée" },
        message
    );
    let response = format!(
        "HTTP/1.1 {}\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        status,
        body.as_bytes().len(),
        body
    );
    let _ = stream.write_all(response.as_bytes());
    let _ = stream.flush();
}

fn read_http_request(stream: &mut TcpStream) -> Result<(String, String), String> {
    stream
        .set_read_timeout(Some(Duration::from_secs(10)))
        .map_err(|error| error.to_string())?;
    let mut buffer = Vec::new();
    let mut chunk = [0u8; 4096];
    let mut expected_total: Option<usize> = None;
    loop {
        let count = stream.read(&mut chunk).map_err(|error| error.to_string())?;
        if count == 0 {
            break;
        }
        buffer.extend_from_slice(&chunk[..count]);
        if buffer.len() > 65536 {
            return Err("Requête OAuth trop volumineuse.".into());
        }
        if expected_total.is_none() {
            if let Some(header_end) = find_header_end(&buffer) {
                let header = String::from_utf8_lossy(&buffer[..header_end]);
                let content_length = header
                    .lines()
                    .find_map(|line| {
                        let (name, value) = line.split_once(':')?;
                        if name.eq_ignore_ascii_case("content-length") {
                            value.trim().parse::<usize>().ok()
                        } else {
                            None
                        }
                    })
                    .unwrap_or(0);
                if content_length > 32768 {
                    return Err("Formulaire OAuth trop volumineux.".into());
                }
                expected_total = Some(header_end + 4 + content_length);
            }
        }
        if expected_total.is_some_and(|total| buffer.len() >= total) {
            break;
        }
    }
    let header_end = find_header_end(&buffer).ok_or("En-tête HTTP incomplet.")?;
    let header = String::from_utf8_lossy(&buffer[..header_end]);
    let first_line = header.lines().next().unwrap_or("").to_string();
    let body = String::from_utf8_lossy(&buffer[header_end + 4..]).to_string();
    Ok((first_line, body))
}

fn run_desktop_google_auth() -> Result<String, String> {
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .map_err(|error| format!("Impossible de démarrer le retour OAuth local : {error}"))?;
    let port = listener
        .local_addr()
        .map_err(|error| error.to_string())?
        .port();

    let mut state_bytes = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut state_bytes);
    let state = state_bytes.iter().map(|byte| format!("{byte:02x}")).collect::<String>();

    let url = format!(
        "{}?llink_desktop_auth_port={}&llink_desktop_auth_state={}",
        DESKTOP_AUTH_BRIDGE_URL, port, state
    );
    open_system_browser(&url)?;
    listener
        .set_nonblocking(true)
        .map_err(|error| format!("Impossible de préparer le retour OAuth : {error}"))?;

    let deadline = Instant::now() + Duration::from_secs(180);
    while Instant::now() < deadline {
        match listener.accept() {
            Ok((mut stream, _address)) => {
                let (request_line, body) = match read_http_request(&mut stream) {
                    Ok(result) => result,
                    Err(error) => {
                        respond(&mut stream, "400 Bad Request", &error);
                        continue;
                    }
                };
                if !request_line.starts_with("POST /complete ") {
                    respond(&mut stream, "404 Not Found", "Adresse de retour OAuth inconnue.");
                    continue;
                }
                let received_state = form_value(&body, "state").unwrap_or_default();
                let id_token = form_value(&body, "id_token").unwrap_or_default();
                if received_state != state {
                    respond(&mut stream, "401 Unauthorized", "La vérification de sécurité n'a pas abouti.");
                    continue;
                }
                if id_token.len() < 100 || id_token.len() > 12000 || !id_token.starts_with("eyJ") {
                    respond(&mut stream, "400 Bad Request", "Le jeton Firebase reçu est invalide.");
                    continue;
                }
                respond(
                    &mut stream,
                    "200 OK",
                    "Le compte Google est connecté. La session revient maintenant dans l'application.",
                );
                return Ok(id_token);
            }
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(100));
            }
            Err(error) => {
                return Err(format!("Erreur pendant le retour OAuth : {error}"));
            }
        }
    }
    Err("La connexion Google a expiré. Relance la connexion depuis Llink.".into())
}

#[tauri::command]
async fn begin_desktop_google_auth() -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(run_desktop_google_auth)
        .await
        .map_err(|error| format!("Le processus de connexion Google a échoué : {error}"))?
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![begin_desktop_google_auth])
        .run(tauri::generate_context!())
        .expect("Erreur pendant le démarrage de Llink");
}
