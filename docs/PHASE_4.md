# Phase 4 — Confidentialité, export et suppression des données

Branche : phase-4/privacy-data-control  
Objectif : donner aux utilisateurs un contrôle concret sur leurs données cloud et locales, et rendre les suppressions de conversations cohérentes entre appareils.

## 1. Export de données personnelles

- Nouvelle route authentifiée GET /api/data/export.
- Export JSON du document users/{uid} et de ses sous-collections, notamment les conversations, les événements et agrégats de consommation.
- Inclusion des anciens documents global_datasets lorsqu'un champ hérité identifie encore explicitement le propriétaire.
- Téléchargement en pièce jointe, avec Cache-Control no-store.
- L'interface ajoute les conversations locales et les préférences personnelles de l'appareil courant.
- L'utilisateur anonyme peut exporter ses données locales ; l'export cloud exige une connexion.

## 2. Suppression synchronisée de l'historique

- Nouvelle route DELETE /api/history/{sync_id} pour effacer une conversation cloud du compte authentifié.
- Nouvelle route DELETE /api/history pour effacer tout l'historique cloud du compte.
- Nouvelle table Dexie deletedChats en version 4 : les tombstones enregistrent l'UID propriétaire, l'identifiant de synchronisation et la date.
- Lors d'une suppression hors ligne, la copie locale est retirée et le tombstone reste en attente.
- À la reconnexion, les suppressions en attente sont envoyées avant la restauration ; les éléments encore en attente sont filtrés pour empêcher leur réapparition locale.
- Chaque lecture et suppression reste limitée au compte Firebase authentifié.

## 3. Suppression du compte

- Nouvelle route authentifiée DELETE /api/account.
- Confirmation écrite exacte : SUPPRIMER MON COMPTE.
- Reconnexion Firebase récente obligatoire : auth_time doit dater de moins de dix minutes.
- Suppression récursive de l'arbre Firestore users/{uid}, y compris les sous-collections de conversations et d'usage.
- Suppression des compteurs pseudonymisés de api_rate_limits calculés pour cet UID.
- Suppression des anciens documents d'amélioration encore explicitement rattachés à l'UID.
- Suppression du compte Firebase Auth après le nettoyage Firestore.
- Le client efface ensuite les conversations et préférences personnelles locales, puis ferme la session.

## 4. Limites, sécurité et quotas

- Les routes de données privées exigent Firebase Auth et Firestore ; aucune suppression cloud n'est exécutée depuis une session anonyme.
- Les opérations ont des quotas séparés : suppression historique 20/minute et 100/jour ; export 2/minute et 10/jour ; suppression de compte 1/minute et 2/jour.
- CORS autorise explicitement la méthode DELETE.
- Les erreurs de stockage sont signalées sans déclarer une suppression réussie.
- Une suppression de compte partiellement terminée est rejouable : les documents déjà effacés ne sont pas recréés.
- Les données anonymisées sans identifiant propriétaire ne peuvent pas être liées à une demande individuelle.
- Les sauvegardes gérées par Firebase/Google ne sont pas effacées immédiatement par les routes Llink.

## 5. Hors périmètre et décisions encore ouvertes

- Aucun délai légal de conservation n'est fixé par cette phase ; CRYPT doit approuver les durées pour l'historique, les sauvegardes, les logs, les quotas et les données consenties.
- La collecte d'amélioration reste désactivée par défaut.
- La Phase 4 ne modifie ni les modèles IA, ni les intensités NORMAL / EXTRA / ULTIME, ni les tarifs, ni les droits d'abonnement, ni l'intégration de paiement Think (Phase 7).
- Aucun déploiement Render/Vercel n'est déclenché par cette branche.

## 6. Validation

Tests de contrat, d'autorisation, d'isolation entre utilisateurs, d'export des sous-collections, de suppression idempotente, de purge de compte et de CORS DELETE à exécuter dans CI.
