# Connexion commune Think–Llink et abonnements Llink

## Architecture

Think est la source de vérité pour l'identité et la facturation.

1. L'utilisateur saisit son e-mail et son mot de passe dans le formulaire Think de Llink.
2. Llink envoie les identifiants à `POST /api/auth/login` de Think. Le mot de passe n'est pas envoyé au backend Llink.
3. Après authentification, Llink demande un ticket SSO signé par Think via `POST /api/auth/llink/exchange`. Ce ticket est limité à Llink, valable deux minutes et utilisable une seule fois.
4. Llink valide le ticket, consomme son identifiant anti-rejeu, puis demande à Firebase Admin une session Firebase personnalisée. L'historique et les services Llink existants continuent donc d'utiliser les sessions Firebase.
5. À chaque vérification des droits, Llink consulte Think. Les claims de session ne définissent pas le forfait : les droits actifs sont lus dans la base Think.

Google reste disponible pour la connexion historique. Les abonnements gérés par Think nécessitent une session issue du compte Think.

## Variables Render — service Think

Définir sur le service backend Think :

| Variable | Valeur |
|---|---|
| `LLINK_SSO_SECRET` | Secret aléatoire partagé avec Llink, au moins 32 caractères |
| `LLINK_SERVICE_TOKEN` | Autre secret aléatoire, distinct du précédent, partagé avec Llink |
| `LLINK_PLAN_PRICES_CDF` | Objet JSON définissant les quatre tarifs CDF |
| `LLINK_PUBLIC_BASE_URL` | URL HTTPS de Llink, par défaut `https://ll-one-self.vercel.app` |

Générer chaque secret séparément sur un terminal local :

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Ne pas mettre les secrets dans GitHub, dans le HTML, dans les journaux ou dans un message public.

Exemple de structure tarifaire uniquement — remplace les montants par les prix décidés pour Llink :

```json
{"bronze":500,"silver":1500,"gold":3000,"diamant":5000}
```

Les quatre clés sont obligatoires. Chaque montant doit être un entier en CDF, multiple de 5, compris entre 100 et 2 500 000. Aucun prix n'est codé en dur dans le navigateur. Tant que cette variable n'est pas valide, le catalogue et le checkout répondent en erreur contrôlée et aucun paiement ne peut être lancé.

Les variables CinetPay existantes doivent aussi être présentes sur Think pour le PayIn Sandbox : `CINETPAY_ENABLED`, `CINETPAY_MODE`, `CINETPAY_API_KEY_CD`, `CINETPAY_API_PASSWORD_CD`, `CINETPAY_CURRENCY=CDF`, `CINETPAY_NOTIFY_URL` et `THINK_PUBLIC_BASE_URL`. Utiliser les clés Sandbox pour les essais.

## Variables Render — service Llink

Définir sur le backend Llink :

| Variable | Valeur |
|---|---|
| `THINK_API_BASE_URL` | `https://think-crypt-entreprise.onrender.com` |
| `THINK_SSO_SECRET` | Exactement la valeur de `LLINK_SSO_SECRET` sur Think |
| `THINK_SERVICE_TOKEN` | Exactement la valeur de `LLINK_SERVICE_TOKEN` sur Think |

Ne pas générer un deuxième secret différent côté Llink : recopier les deux valeurs Think dans les variables correspondantes de Llink. Le projet Firebase Admin/Firestore de Llink doit rester configuré, notamment pour l'anti-rejeu des tickets SSO en production.

Si `CORS_ORIGINS` est défini explicitement sur Think, y autoriser l'origine web Llink utilisée dans le navigateur. La configuration CORS doit autoriser les en-têtes `Authorization` et `Content-Type`.

## Route d'abonnement et paiement

Routes Llink :

- `GET /api/subscriptions/catalog` — catalogue et tarifs CDF lus depuis Think.
- `GET /api/subscriptions/payment-options` — numéros Mobile Money masqués déjà enregistrés dans Think.
- `POST /api/subscriptions/checkout` — demande un checkout ; le client transmet le forfait et l'opérateur, jamais le montant.
- `GET /api/subscriptions/status` — statut d'abonnement.
- `POST /api/subscriptions/refresh` — retour CinetPay : demande à Think de reconsulter directement le statut fournisseur.

Think calcule le montant, crée la transaction CinetPay et conserve l'abonnement Llink dans une table distincte du portefeuille. Un paiement Llink confirmé n'ajoute aucun crédit au portefeuille Think. L'abonnement ne devient actif qu'après une réponse fournisseur vérifiée `SUCCESS`. Une notification de navigateur ou un paramètre d'URL ne peut pas l'activer.

Le renouvellement d'un abonnement actif commence après son expiration courante. Les statuts en attente ne donnent pas accès au forfait.

## Tests et limite du lancement

La CI valide les échanges SSO (ticket valide, expiré, mauvais scope et rejeu), l'autorisation des checkouts, les tarifs CDF, l'activation sur confirmation CinetPay, la non-création de crédit Think, les renouvellements, la syntaxe JavaScript/iframe et les smoke tests Sandbox existants.

La CI ne réalise aucun appel de paiement réel. Après avoir ajouté les variables Render et fusionné les deux PR, il faudra effectuer une connexion réelle Think → Llink, puis un paiement CinetPay Sandbox avec un compte de test. Le déploiement de ces branches n'est pas considéré comme validé tant que cet essai coordonné n'a pas réussi.


## Identité universelle CRYPT — INK ID

L'identifiant stable du compte est désormais `crypt_id`, au format `INK_` suivi de 15 caractères alphanumériques majuscules. Think le génère et le conserve ; le `think_id` (`THK-...`) reste présent pour la compatibilité historique.

Le formulaire de connexion Llink accepte l'INK ID **ou** l'adresse e-mail et transmet la valeur au champ API historique `email` de `POST /api/auth/login`. Le mot de passe est toujours vérifié par Think. Llink ne stocke pas le mot de passe Think.

Le ticket SSO Think signé contient obligatoirement :
- `sub` : identifiant interne du compte Think ;
- `think_id` : identifiant Think historique ;
- `crypt_id` : INK ID universel vérifié ;
- `scope=llink`, `iss=think-api`, `aud=llink-api`, expiration courte et `jti` unique.

Llink rejette tout INK ID mal formé, ticket expiré, mauvaise audience, mauvais scope ou ticket rejoué. Le claim Firebase `crypt_id` est disponible pour l'interface et les futures intégrations. L'UID Firebase basé sur le Think ID historique est conservé afin de ne pas perdre l'accès aux conversations et fichiers existants.

Dans l'interface Llink, l'accès au Compte CRYPT se trouve dans le sélecteur des produits CRYPT (entrée « Compte CRYPT » à côté des produits). Le bouton de connexion isolé de l'écran principal a été retiré. La connexion Google historique reste uniquement pour assurer la compatibilité des anciens comptes Llink ; elle ne lie pas automatiquement un compte Google à un INK ID.

L'INK ID est l'identité, pas une autorisation globale : chaque application doit encore associer explicitement ses propres profils locaux à cette identité et appliquer ses rôles/permissions propres. La présente intégration SSO couvre Think et Llink ; les autres produits du sélecteur ne sont pas considérés comme raccordés tant que leur backend n'a pas implémenté ce contrat.
