# Cycle de vie et suppression des données — Llink

## État livré après la Phase 4

- Les conversations synchronisées sont stockées sous users/{uid}/chats dans Firestore.
- L'historique local est stocké dans IndexedDB (Dexie) sur l'appareil.
- GET /api/data/export permet à un utilisateur authentifié de télécharger son document de compte, ses sous-collections Firestore, ses compteurs d'usage et les anciens enregistrements d'amélioration encore liés explicitement à son UID.
- L'application ajoute à l'export les conversations et préférences personnelles présentes sur l'appareil courant.
- DELETE /api/history/{sync_id} supprime une conversation cloud ; DELETE /api/history supprime l'historique cloud du compte.
- Les suppressions individuelles faites hors ligne sont mises en attente dans Dexie avec l'UID propriétaire. Elles sont rejouées avant la restauration cloud à la prochaine connexion au même compte.
- La suppression de compte efface récursivement users/{uid} et ses sous-collections, les compteurs api_rate_limits dérivés de cet UID, les anciens documents global_datasets encore identifiables par UID, puis le compte Firebase Auth.
- La suppression du compte exige un jeton dont auth_time date de moins de dix minutes et une confirmation écrite exacte.
- La collecte d'amélioration reste désactivée par défaut. Elle exige toujours un drapeau serveur et un consentement explicite par requête.

## Limites connues

- L'export local ne concerne que l'appareil depuis lequel l'utilisateur télécharge le fichier. Les autres appareils doivent être exportés depuis leur propre stockage local ; les données synchronisées apparaissent dans la partie cloud.
- Les anciens enregistrements de global_datasets qui ne contiennent plus aucun identifiant de propriétaire sont anonymisés et ne peuvent pas être rattachés à un compte individuel. Ils ne sont ni exportés ni supprimés au titre d'une demande individuelle.
- Les sauvegardes gérées par Firebase/Google, les journaux internes du fournisseur et les copies de sauvegarde d'un appareil suivent leurs propres mécanismes et délais ; les routes Llink ne peuvent pas promettre leur effacement immédiat.
- Si la suppression du compte échoue après la suppression Firestore mais avant la suppression Firebase Auth, l'API retourne 503. Une nouvelle tentative peut terminer la suppression ; les documents déjà effacés ne sont pas recréés.
- Une suppression hors ligne est locale immédiatement, mais sa propagation cloud attend la prochaine connexion de l'utilisateur propriétaire. Tant qu'elle est en attente, le client masque la conversation pendant la restauration.
- La suppression locale d'un compte efface les conversations et les préférences personnelles llink_ sur l'appareil utilisé. Les autres appareils ne sont pas contrôlés à distance par cette opération.

## Règles opérationnelles immédiates

1. Ne pas activer ENABLE_DATASET_COLLECTION tant qu'un écran de consentement, une procédure de retrait et une procédure de suppression des enregistrements concernés ne sont pas opérationnels.
2. Ne pas utiliser global_datasets pour l'entraînement avant revue des anciens enregistrements et validation de la provenance/du consentement.
3. Ne pas inscrire les prompts, réponses, jetons Firebase, clés fournisseurs, références de paiement ou données d'identité dans les journaux.
4. Les historiques cloud restent accessibles uniquement au propriétaire authentifié.
5. Une suppression effectuée dans l'interface doit distinguer clairement l'état local et l'état cloud lorsqu'une connexion est indisponible.

## Politique de conservation à approuver

La Phase 4 implémente l'accès et la suppression à la demande, mais ne fixe pas de durée légale de conservation et ne change pas les paramètres de sauvegarde Firebase. CRYPT doit encore approuver des durées explicites pour :
- l'historique cloud et les suppressions demandées ;
- les sauvegardes Firestore ;
- les journaux techniques ;
- les compteurs de quotas ;
- les données d'amélioration collectées avec consentement.

Ces délais doivent être décidés selon les obligations applicables et les conditions réelles des fournisseurs ; aucune durée n'est inventée par le code.

## Sources de données et portée de l'export

- Document de compte : users/{uid}.
- Historique : users/{uid}/chats.
- Mesure d'usage : users/{uid}/usage_hours et users/{uid}/usage_events.
- Quotas : documents pseudonymisés de api_rate_limits, supprimés lors d'une suppression de compte.
- Anciens échanges encore liés : requêtes sur global_datasets avec les champs hérités uid, user_uid, user_id ou userId.
- Agrégat anonyme : system_usage_hours, non rattaché à un compte.

## Statut

Les routes d'export et de suppression sont livrées dans la Phase 4. La collecte d'amélioration reste inactive. Les durées de conservation, les sauvegardes gérées par Firebase et la suppression de données réellement anonymisées restent des limites documentées et des décisions opérateur/juridiques.
