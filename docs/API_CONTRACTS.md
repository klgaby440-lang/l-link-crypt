# Llink — contrats HTTP existants

Ce document décrit le contrat conservé pendant la phase 1. Les réponses d'erreur textuelles historiques sont documentées afin que le frontend puisse continuer à les afficher ; elles ne constituent pas encore le format d'erreur cible.

## Disponibilité

### `GET /`

Réponse :

```json
{"message": "Llink Backend API est opérationnel."}
```

## Compte et abonnement

### `GET /api/user/status`

En-tête : `Authorization: Bearer <Firebase ID token>`.

Pour une session anonyme ou une base indisponible :

```json
{"isValid": false, "expirationDate": null, "isNewUser": false}
```

Pour un compte connu, la réponse contient `isValid`, `isTrial`, `expirationDate` (millisecondes Unix) et `isNewUser`.

### `POST /api/verify-payment`

Corps :

```json
{"transactionId": "reference"}
```

La route conserve le contrat `{"success": bool}`. L'ancienne activation Pro reposant uniquement sur une référence fournie par le navigateur a été désactivée. La route renvoie `{"success": false}` tant que la validation serveur via Think n'est pas intégrée. Une session non authentifiée reçoit HTTP 401.

## Chat

### `POST /api/chat`

Corps :

```json
{
  "message": "Bonjour",
  "model": "gemini-1.5-flash",
  "preferences": "réponses courtes",
  "mode": "chat",
  "source": "llink_web",
  "data_collection_consent": false
}
```

Champs obligatoires : `message`, `model`. Les autres champs sont facultatifs. `mode` vaut notamment `chat` ou `translate`. Le nouveau champ `data_collection_consent` vaut `false` par défaut et reste rétrocompatible avec les anciennes versions du frontend.

Réponse : flux de fragments texte bruts avec le type MIME historique `text/event-stream`. Il ne s'agit pas d'un flux d'événements JSON contenant des objets `data:`.

Les choix de modèle et le fallback restent ceux du serveur précédent ; leur centralisation dans un registre de capacités est réservée à la phase 3.

## Médias

### `POST /api/ocr`

Corps JSON : `{"imageBase64": "data:image/jpeg;base64,..."}`.

Réponse : `{"response": "texte extrait ou message d'erreur"}`.

### `POST /api/audio`

Envoi multipart avec le champ fichier `file`.

Réponse : `{"text": "transcription ou message d'erreur"}`.

## Historique

### `POST /api/history/sync`

Corps : objet conversation JSON. Avec un compte anonyme ou Firestore indisponible, la réponse est `{"status": "skipped"}`. En cas d'écriture, `{"status": "success"}`.

### `GET /api/history`

Réponse : `{"chats": [...]}`. Si Firestore est indisponible, une propriété `warning` peut être ajoutée.

## Authentification — limite connue à traiter en phase 2

Le comportement historique est conservé pour la compatibilité : un jeton absent ou invalide est traité comme une session anonyme. Cette tolérance ne doit pas être considérée comme une politique d'autorisation suffisante pour la production. La phase 2 remplacera ce comportement par une matrice d'accès explicite et des réponses 401/403 adaptées.
