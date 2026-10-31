# Phase 2 — Sécurité, disponibilité et maîtrise des coûts

**Branche :** `phase-2/security-quotas-cost-controls`  
**Point de départ :** `main` après fusion et tests de la Phase 1  
**État :** implémentation et tests CI ; validation de l'environnement Render/Firestore à effectuer avant mise en production.

## Politique d'accès

| Route / fonction | Anonyme | Compte Firebase valide |
|---|---:|---:|
| `GET /api/user/status` | Oui, réponse non abonnée | Oui |
| `POST /api/chat` | Oui, quota réduit | Oui, quota supérieur |
| `POST /api/ocr` | Oui, quota réduit | Oui, quota supérieur |
| `POST /api/audio` | Oui, quota réduit | Oui, quota supérieur |
| `GET /api/history` | 401 | Oui |
| `POST /api/history/sync` | 401 | Oui |
| `POST /api/verify-payment` | 401 | Oui, sans activation tant que Think n'est pas prêt |

Un en-tête Bearer fourni mais invalide, expiré, révoqué ou désactivé retourne 401 : il n'est jamais requalifié en session anonyme. Une indisponibilité de Firebase retourne 503.

## Quotas par défaut

Les quotas sont des plafonds de protection provisoires, identiques pour tous les niveaux d'abonnement. Ils ne constituent pas encore les crédits de consommation par offre ; le suivi financier par modèle/fonction sera défini dans la Phase 3.

| Fonction | Anonyme / minute | Anonyme / UTC jour | Compte / minute | Compte / UTC jour |
|---|---:|---:|---:|---:|
| Chat | 3 | 20 | 12 | 240 |
| OCR | 1 | 5 | 5 | 40 |
| Audio | 1 | 3 | 3 | 20 |
| Historique (lecture) | — | — | 30 | 200 |
| Historique (écriture) | — | — | 30 | 500 |
| État utilisateur | 3 | 20 | 30 | 300 |
| Vérification de paiement | — | — | 3 | 10 |

Les compteurs de production résident dans la collection Firestore `api_rate_limits`. Chaque couple utilisateur/fonction possède un document stable, mis à jour dans une transaction atomique. Les identifiants de document sont hachés ; les IP brutes ne sont pas conservées. La réponse de dépassement est HTTP 429 avec `Retry-After`.

En développement/tests uniquement, un compteur mémoire permet de travailler sans Firebase. En production, l'absence de Firestore bloque les fonctions à coût variable avec HTTP 503 : aucun accès IA n'est accordé sans compteur vérifiable.

## Limites techniques

- Corps HTTP : 13 500 000 octets maximum.
- Image : 6 000 000 octets maximum, formats JPEG, PNG et WebP.
- Audio : 12 000 000 octets maximum, formats WebM, MP4, MP3, WAV, OGG et AAC.
- Message : 12 000 caractères maximum.
- Préférences injectées dans le prompt : 2 000 caractères maximum.
- Réponse Gemini/Hugging Face : plafond configuré à 2 048 tokens.
- Timeout fournisseur : 60 secondes par défaut.
- Concurrence IA : 4 requêtes par processus ; attente maximale de file : 3 secondes.
- Erreurs de fournisseur : message client générique ; aucun corps de réponse fournisseur ou secret n'est renvoyé au navigateur.

Les valeurs sont surchargeables via les variables d'environnement décrites dans [API_SECURITY.md](API_SECURITY.md).

## Mesures de configuration à appliquer sur Render

1. Définir explicitement `APP_ENV=production`.
2. Maintenir `FIREBASE_CONFIG`, `GEMINI_API_KEY` et `HF_TOKEN` dans les variables secrètes Render.
3. Vérifier que le compte de service Firebase Admin peut lire et écrire dans `api_rate_limits`, les collections utilisateur et l'historique.
4. Ne pas activer une origine CORS générique `*`.
5. Vérifier le vrai comportement de `request.client.host` derrière le proxy Render ; ne jamais accepter un `X-Forwarded-For` arbitraire sans configurer explicitement les proxys de confiance.

## Cycle de vie des données\n\nLa collecte d'amélioration reste désactivée par défaut et l'interface actuelle ne transmet aucun consentement. Les historiques cloud sont conservés dans Firestore ; la suppression cloud cohérente et la fermeture de compte relèvent de la Phase 4. Les anciennes entrées éventuelles de `global_datasets` ne sont pas supprimées automatiquement par cette PR et doivent faire l'objet d'une revue et d'une politique de conservation approuvée avant tout nouvel entraînement. Les journaux ne doivent contenir ni prompts, ni réponses, ni tokens, ni identifiants directs. Voir `docs/DATA_LIFECYCLE.md`.\n\n## Limites restantes

- Le quota anonyme est fondé sur l'adresse réseau observée par ASGI ; il ne remplace pas un WAF/anti-bot distribué.
- La concurrence IA est locale à chaque processus, tandis que les quotas Firestore sont distribués.
- Les plafonds sont des garde-fous d'usage, pas encore une facturation exacte par fournisseur.
- Les transactions de quota doivent être vérifiées sur le projet Firestore réel avant ouverture publique.
- La vérification du paiement reste désactivée jusqu'à l'intégration serveur-à-serveur de Think (Phase 7).

## Validation

Les tests automatisés couvrent la réponse 401 des routes privées, le refus d'un faux jeton, la limite anonyme, les limites de fichiers et les erreurs fournisseur. La Phase 2 ne sera considérée comme validée qu'après CI vert et recette en environnement Render/Firestore.
