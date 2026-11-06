# Intégration Llink — CRYPT Billing & Treasury

**Statut :** spécification d'intégration et plan de migration, pas encore une implémentation fonctionnelle.  
**Dépôt :** `l-link-crypt`  
**Branche documentaire :** `crypt-billing-architecture`

La spécification centrale se trouve dans le dépôt Think :  
[`docs/CRYPT_BILLING_TREASURY_ARCHITECTURE.md`](https://github.com/klgaby440-lang/think-crypt-entre/blob/crypt-billing-architecture/docs/CRYPT_BILLING_TREASURY_ARCHITECTURE.md)

## 1. Décisions produit confirmées

- Les comptes Llink (Firebase Auth) et Think restent distincts ; l'utilisateur peut les relier et retirer cette liaison.
- Les abonnements Llink sont payés exclusivement depuis le portefeuille Think pour le MVP.
- Un utilisateur sans solde suffisant doit d'abord alimenter son portefeuille Think, puis revenir payer sa facture Llink.
- Les recettes Llink et Think alimentent une trésorerie commune CRYPT, mais chaque écriture garde une source analytique propre.
- Llink ne reçoit jamais les identifiants ni les secrets du compte Think.
- Llink ne considère jamais qu'un paiement est réussi à partir d'un retour navigateur ou d'une référence fournie par le client.

## 2. Situation actuelle observée

Llink utilise Firebase Authentication et Firestore. Le backend FastAPI valide les Firebase ID tokens avec contrôle de révocation. Les informations d'abonnement et les droits sont actuellement matérialisés dans Firestore.

La route `POST /api/verify-payment` de `llink_api/api/routes/users.py` retourne actuellement `{"success": false}` et indique dans le code que l'activation Pro est en attente d'une confirmation Think indépendante côté serveur. Cette route est donc un point d'intégration à remplacer de manière contrôlée, pas une preuve d'un paiement existant.

Le endpoint `GET /api/user/status` crée encore une période d'essai pour un nouveau compte et lit `isPro`, `expirationDate`. Les niveaux de plan actuellement référencés dans la documentation de sécurité sont `bronze`, `silver`, `gold`, `diamant`. La migration doit maintenir l'essai existant et éviter qu'une facture impayée ne donne un droit payant.

Références de code :
- `llink_api/api/routes/users.py` : statut utilisateur et vérification paiement.
- `llink_api/security.py` : vérification Firebase.
- `llink_api/services/entitlements.py` : résolution du niveau autorisé.
- `llink_api/api/routes/usage.py` : application des droits et compteurs.
- `docs/API_CONTRACTS.md` : contrats frontend/backend actuels.

## 3. Rôle exact de Llink

Llink est le **consommateur des droits d'abonnement**, pas le système financier de référence.

Llink reste responsable de :
- authentifier l'utilisateur avec Firebase ;
- demander la liaison à Think après action explicite de l'utilisateur ;
- afficher les tarifs et factures retournés par Think Billing ;
- ouvrir Think pour autoriser la liaison ou effectuer le paiement ;
- recevoir les événements Billing signés depuis Think ;
- appliquer dans Firestore une copie des droits confirmés ;
- résoudre les niveaux d'accès IA et limiter modèles, quotas et fonctions ;
- afficher l'état « payé, activation en cours » si l'événement n'a pas encore été appliqué.

Llink ne doit pas :
- débiter un portefeuille ;
- créer un montant à partir d'un prix local JavaScript ;
- accepter une transactionId libre comme preuve ;
- activer `isPro` sur la base d'une réponse du frontend ;
- avoir accès au solde ou à l'historique complet du portefeuille Think.

## 4. Liaison de compte Think

### 4.1 Table locale de correspondance côté Think

La liaison canonique est conservée côté Think PostgreSQL dans `account_links` :

- `think_user_id` ;
- `llink_firebase_uid` ;
- `status` ;
- dates de consentement et révocation ;
- version du texte de consentement.

Llink peut garder une métadonnée miroir minimale dans Firestore (par exemple `billingLinkStatus`, `linkedAt`, `thinkPublicId` si nécessaire), mais cette copie ne devient jamais la source de vérité. Ne pas y stocker les jetons Think.

### 4.2 Parcours côté Llink

1. Exiger une session Firebase valide.
2. Le backend Llink crée une `link_session` contenant l'UID Firebase authentifié, un `state` aléatoire haché, nonce, PKCE verifier/challenge et expiration 5–10 minutes.
3. Le navigateur est redirigé vers le point d'autorisation Think avec uniquement les paramètres OAuth nécessaires.
4. Think authentifie et fait consentir l'utilisateur au compte Think qui sera lié.
5. Think renvoie un code temporaire au callback Llink allowlisté.
6. Le backend Llink valide state/nonce, échange le code avec Think (client confidentiel + PKCE) et finalise la relation Think ID ↔ UID Firebase à partir du résultat serveur. L'UID Firebase provient de la session préalablement validée, pas de query/body soumis par le navigateur.
7. Llink confirme la liaison dans son interface.

### 4.3 Routes Llink à ajouter

- `POST /api/account-links/think/start` : authentification Firebase obligatoire ; ouvre une session de liaison.
- `GET /api/account-links/think/callback` : valide state/code puis échange le code de façon serveur-à-serveur.
- `GET /api/account-links` : retourne uniquement l'état de liaison du compte connecté.
- `DELETE /api/account-links/think` : révoque la liaison après confirmation et reauthentification si nécessaire.

La révocation arrête les prochains achats Llink via Think et les nouveaux renouvellements. Elle ne supprime aucune facture historique ni écriture comptable.

## 5. Authentification serveur-à-serveur Think ↔ Llink

Les appels privilégiés utilisent un client Llink confidentiel enregistré côté Think.

Préférence : client assertion JWT signée (clé privée Llink, clé publique enregistrée côté Think), RS256 ou EdDSA, durée ≤ 5 minutes, audience explicite, `jti` anti-rejeu, scopes minimaux et rotation des clés.

Transition possible si le client JWT n'est pas disponible : secret haute entropie exclusivement dans Render, HMAC-SHA256 sur méthode + chemin + timestamp + nonce + hash du corps, tolérance temporelle courte, nonce unique et rotation documentée. Jamais de secret dans `app/index.html`, Capacitor ou Git.

Scopes recommandés :
- `billing:catalog:read`
- `billing:invoice:create`
- `billing:invoice:read`
- `billing:subscription:read`
- `billing:events:receive`

Ne pas accorder `wallet:read`, `wallet:debit` ou `treasury:read` à Llink. Le paiement wallet est orchestré par Think Billing après une demande de facture, avec identité et lien vérifiés.

## 6. Contrat de facturation

### 6.1 Lire le catalogue

Llink Backend → Think :

`GET /api/v1/billing/catalog?product_code=llink`

La réponse contient les SKUs actifs, libellés, montants entiers, devise, période et version de tarif. Le frontend présente cette réponse ; il ne calcule ni ne modifie les prix.

### 6.2 Créer une facture

Llink Backend → Think :

`POST /api/v1/billing/invoices`

Corps logique :

```json
{
  "product_code": "llink",
  "sku": "llink.<plan>.<period>",
  "beneficiary_subject_id": "<Firebase UID validé côté Llink>",
  "idempotency_key": "<UUID généré côté backend Llink>"
}
```

Think doit ignorer toute donnée d'identité soumise non vérifiée et utiliser le sujet issu de la liaison. Le plan et le montant sont obtenus depuis le SKU du catalogue. L'appel est authentifié avec le client technique Llink.

### 6.3 Payer depuis Think Wallet

Llink ne débite jamais le portefeuille lui-même. L'interface affiche une action « Payer avec mon portefeuille Think » qui ouvre Think ou déclenche un parcours de paiement hébergé par Think.

Le backend Think :
- vérifie la session propriétaire du portefeuille ;
- vérifie la liaison active et la facture ;
- débite le portefeuille dans une transaction PostgreSQL atomique ;
- écrit le ledger wallet, la facture payée, la souscription, les lignes Treasury et l'événement outbox ;
- retourne le statut du paiement et son identifiant.

Si le solde est insuffisant, Think répond avec l'état structuré `INSUFFICIENT_WALLET_BALANCE`. L'utilisateur recharge alors le portefeuille dans Think (ex. PayIn CinetPay), puis relance le paiement de la facture. Le paiement de l'abonnement ne doit pas appeler directement CinetPay.

### 6.4 Lire l'état

Llink Backend → Think :

`GET /api/v1/billing/invoices/{invoice_id}`

Puis :

`GET /api/v1/billing/subscriptions?product_code=llink`

Une référence de facture n'est jamais suffisante pour accéder au dossier d'un autre utilisateur : Think vérifie la liaison et le client technique.

## 7. Événements de droits — outbox

Think crée l'événement dans la même transaction SQL que le débit wallet et le paiement de facture. Un dispatcher envoie après commit à une route Llink réservée au client technique.

Événements :
- `subscription.activated.v1`
- `subscription.renewed.v1`
- `subscription.expiring.v1`
- `subscription.expired.v1`
- `subscription.cancelled.v1`
- `subscription.refunded.v1`
- `account_link.revoked.v1`

Endpoint proposé :

`POST /internal/billing/events`

Llink :
1. authentifie le client et la signature ;
2. vérifie le timestamp et le `event_id` ;
3. stocke l'ID traité avec contrainte unique ;
4. vérifie `product_code=llink` et mappe le `plan_code` vers le `subscriptionPlan` Llink ;
5. met à jour Firestore Admin SDK côté serveur : `isPro`, `expirationDate`, `subscriptionPlan`, `billingSubscriptionId`, `billingInvoiceId`, `billingEventVersion` ;
6. enregistre un résultat d'application pour audit ;
7. répond avec un ACK idempotent.

Ne jamais faire cette mise à jour Firestore depuis le navigateur. En cas d'erreur Firestore, répondre en erreur transitoire afin que Think réessaie. Les événements déjà traités doivent répondre en succès idempotent sans rallonger une deuxième fois la période.

Payload indicatif :

```json
{
  "event_id": "evt_<uuid>",
  "event_type": "subscription.activated.v1",
  "schema_version": 1,
  "occurred_at": "ISO-8601 UTC",
  "product_code": "llink",
  "subject_id": "<Firebase UID>",
  "subscription_id": "<Think subscription public id>",
  "invoice_id": "<Think invoice public id>",
  "plan_code": "<bronze|silver|gold|diamant>",
  "period_start": "ISO-8601 UTC",
  "period_end": "ISO-8601 UTC",
  "currency": "CDF",
  "amount_minor": 0
}
```

Le montant indiqué est celui de la facture ; il n'accorde aucun droit à lui seul. L'événement est signé et validé côté serveur. L'exemple `amount_minor=0` est un placeholder de schéma, pas un prix.

## 8. Compatibilité avec les droits existants

Actuellement :
- `/api/user/status` gère le trial initial et lit les champs `isPro` et `expirationDate`.
- La documentation sécurité attend `subscriptionPlan` dans `bronze`, `silver`, `gold`, `diamant`.
- `resolve_entitled_level` est l'autorité des niveaux d'accès et ne doit pas faire confiance au client.
- `POST /api/verify-payment` retourne aujourd'hui toujours `success: false`.

Migration :
1. Garder les champs et la réponse frontend de `/api/user/status` compatibles.
2. Déplacer l'autorité de l'abonnement payant vers l'événement Billing confirmé.
3. Mapper centralement les SKU Billing vers les plans et niveaux internes Llink.
4. Préserver un essai gratuit existant si aucune souscription payante confirmée n'a été activée.
5. Un paiement échoué, une facture ouverte ou un event non authentifié ne doit jamais définir `isPro=true`.
6. Remplacer `/api/verify-payment` par une vérification serveur-à-serveur de l'état Billing ; ne plus accepter qu'une référence de transaction envoyée par le navigateur.
7. Garder la lecture d'accès performante : Firestore contient une projection des droits confirmés, synchronisée par événements et réconciliée périodiquement.

## 9. UX à ajouter

### Paramètres / Comptes connectés
- Afficher Think : connecté / non connecté.
- Bouton « Connecter mon compte Think ».
- Afficher le compte Think lié avec identifiant public partiellement masqué.
- Bouton « Déconnecter Think » avec confirmation et explication des conséquences.
- Ne jamais demander ni afficher le mot de passe Think dans Llink.

### Abonnement
- Afficher les plans et prix retournés par le catalogue Think.
- Montrer clairement devise et période.
- CTA « Payer avec mon portefeuille Think ».
- Si solde insuffisant : montant nécessaire et CTA « Recharger dans Think ».
- Afficher états : facture créée, paiement en cours, payé / activation en cours, actif, expiration proche, expiré, annulé, remboursé.
- Après paiement : attendre l'ACK événement Llink, puis rafraîchir les droits serveur ; ne pas activer immédiatement sur la seule réponse de l'interface.

## 10. Configuration d'environnement à prévoir

Côté Think Render :
- `LLINK_OAUTH_CLIENT_ID`
- `LLINK_OAUTH_PUBLIC_KEY` ou configuration client assertion équivalente
- `LLINK_OAUTH_REDIRECT_URI` exacte et allowlistée
- URL/API callback Llink si Think pousse les événements
- secret/clé de signature des événements
- clés séparées staging/sandbox et production.

Côté Llink Render :
- `THINK_BILLING_BASE_URL`
- `THINK_OAUTH_CLIENT_ID`
- `THINK_OAUTH_CLIENT_PRIVATE_KEY` (secret de service, jamais public)
- `THINK_OAUTH_REDIRECT_URI`
- `THINK_BILLING_EVENT_PUBLIC_KEY` ou secret HMAC transitoire
- `THINK_OAUTH_SCOPES`.

Les noms ci-dessus sont des noms de configuration proposés. Ils ne sont pas encore lus par le code actuel. Ajouter la validation de configuration au démarrage et ne pas renseigner les valeurs de production avant validation des clés et du domaine.

## 11. Plan d'implémentation dans Llink

### L1 — Contrat et configuration
- Verrouiller le contrat Think Billing et la version d'événement.
- Ajouter la configuration typée et validée pour l'URL Think et le client confidentiel.
- Tester l'absence de secret côté frontend.

### L2 — Account Linking
- Créer `link_sessions` Firestore ou stockage serveur éphémère durable avec state hash, nonce, verifier PKCE, Firebase UID et expiration.
- Implémenter routes start/callback/status/unlink.
- Tests CSRF, PKCE, code replay, state expiré, compte déjà lié et révocation.

### L3 — Client Think Billing
- Ajouter un client HTTP backend, timeouts, retries bornés, circuit breaker et logs redacted.
- Implémenter lecture catalogue, création/lecture facture, lecture abonnement.
- Auth client assertion et validation de l'audience/scopes.

### L4 — Consommateur d'événements
- Ajouter `processed_billing_events` (Firestore ou stockage durable) avec clé unique.
- Implémenter `POST /internal/billing/events`, signature, anti-rejeu et idempotence.
- Mise à jour Firebase Admin de la projection d'entitlement.
- Ajouter route/admin de replay sécurisé et réconciliation.

### L5 — Frontend
- Vue « Comptes connectés ».
- Remplacer les formulaires d'abonnement locaux par le catalogue Think.
- Paiement hébergé dans Think ; afficher solde insuffisant / facture / état d'activation.
- Conserver UX essai, expiration et sélection de plan existantes.

### L6 — Retrait de l'ancien stub
- Migrer `/api/verify-payment` vers la vérification Billing côté serveur après activation du client.
- Garder une réponse contractuelle stable si le frontend l'utilise encore.
- Ne jamais considérer une ancienne transactionId cliente comme confirmation.

### L7 — Validation
- Tests unitaires des signatures et mappings.
- Tests d'intégration Firebase emulator/Firestore de test et backend Think Sandbox.
- Tests end-to-end de liaison, facture, wallet debit, event, activation, duplicate et retry.
- Tests de révocation et d'abonnement expiré/annulé/remboursé.
- Déploiement progressif derrière feature flag.

## 12. Matrice de tests Llink

- [ ] Un compte Firebase relie son compte Think après double consentement.
- [ ] Un autre Firebase UID ne peut pas réclamer la même liaison.
- [ ] Un compte Think ne peut pas être lié par un tiers sans authentification/consentement du titulaire.
- [ ] State invalide, code expiré, PKCE incorrect ou code rejoué sont rejetés.
- [ ] Llink ne peut pas choisir un prix ou un SKU désactivé.
- [ ] Un compte non lié ne peut pas créer un abonnement facturé sur un autre compte.
- [ ] Solde Think suffisant : une facture et une souscription sont créées ; un seul débit.
- [ ] Solde insuffisant : aucun débit, aucun droit payant.
- [ ] Event signé : entitlement Llink activé une seule fois.
- [ ] Event dupliqué : ACK sans prolonger la période.
- [ ] Firebase/Firestore indisponible : activation en attente et event rejouable.
- [ ] Event expiré, révoqué ou remboursé : droits adaptés selon le contrat.
- [ ] La révocation de la liaison empêche les achats futurs mais conserve les traces.
- [ ] Le frontend ne contient aucune clé technique, signature ni jeton serveur.
- [ ] Les coûts IA, crédits d'usage et limites de modèle restent indépendants des écritures Treasury, sauf agrégation analytique explicitement définie.

## 13. Hors périmètre de cette étape

- Aucun prix n'est fixé ici.
- Aucun code de paiement n'est encore activé.
- Aucun accès au portefeuille Think n'est accordé à Llink.
- Aucun débit, remboursement ou abonnement réel n'est effectué.
- Aucun changement Firebase, Render ou CinetPay n'est appliqué.
- Le document n'autorise pas PayOut réel.

Les montants et périodes doivent être définis dans le catalogue de Think ; les règles comptables et fiscales de CRYPT doivent être validées avant production.
