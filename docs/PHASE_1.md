# Phase 1 — Socle backend et contrats API

**Branche :** `phase-1/backend-core-modularization`  
**Point de départ :** `main` après fusion de la préparation Android  
**État :** implémentation soumise aux tests CI

## Objectif

Rendre le backend lisible et testable sans réécrire l'interface. La commande de lancement existante reste `uvicorn main:app`.

## Structure introduite

```text
main.py
llink_api/
  api/routes/
    chat.py
    health.py
    history.py
    media.py
    users.py
  providers/
    gemini.py
    huggingface.py
  services/
    training_data.py
  config.py
  database.py
  schemas.py
  security.py
tests/
docs/
```

## Compatibilité préservée

Les chemins consommés par l'interface restent présents : `/`, `/api/user/status`, `/api/verify-payment`, `/api/chat`, `/api/ocr`, `/api/audio`, `/api/history/sync` et `/api/history`. Le format texte du streaming et les champs JSON `response`, `text`, `chats` et `status` sont documentés dans [API_CONTRACTS.md](API_CONTRACTS.md).

## Changements de protection indispensables

- La collecte des échanges est maintenant désactivée par défaut. Elle exige à la fois `ENABLE_DATASET_COLLECTION=true` côté serveur et `data_collection_consent=true` dans la requête. Les utilisateurs anonymes ne sont pas collectés.
- L'identifiant Firebase n'est plus copié dans les enregistrements du dataset.
- L'export global automatique vers une adresse e-mail et la commande secrète d'export ne sont pas repris.
- L'ancienne activation Pro fondée sur la longueur d'une référence de transaction ou sur un identifiant de test est désactivée. La route reste disponible avec le même format `success`; la validation réelle attend l'API Think.

Ces changements évitent de perpétuer des mécanismes qui contredisent les règles de la feuille de route (consentement explicite et confirmation de paiement vérifiée).

## Hors périmètre de cette livraison

La politique complète 401/403, les quotas, rate limits, limites de fichiers, anti-abus, normalisation globale des erreurs, le registre de modèles, les adaptateurs définitifs, les métriques de coût, la migration du SDK Gemini, la refonte de la synchronisation et l'intégration Think restent dans leurs phases respectives.

## Vérifications

Le workflow `.github/workflows/backend-tests.yml` exécute les tests de non-régression des contrats principaux. La phase ne sera considérée comme validée qu'après un résultat CI vert et une vérification de déploiement sur un environnement de test.
