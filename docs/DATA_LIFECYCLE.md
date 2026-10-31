# Cycle de vie et suppression des données — Llink

## État effectivement livré

- Les conversations synchronisées sont stockées sous le compte utilisateur dans Firestore.
- L'historique local est stocké dans IndexedDB (Dexie) sur l'appareil.
- La suppression d'une conversation depuis l'interface actuelle agit localement ; la suppression correspondante dans Firestore n'est pas encore synchronisée.
- La restauration cloud ne fournit pas encore un mécanisme complet d'export, de suppression de compte ou de suppression synchronisée.
- La collecte d'amélioration est inactive par défaut. Elle exige un drapeau serveur et un consentement explicite par requête ; l'interface actuelle ne fournit pas encore ce consentement.
- Les entrées historiques éventuelles de `global_datasets` ne sont pas purgées par la Phase 2. Leur existence et leur volume doivent être audités dans Firestore avant toute campagne d'entraînement.
- Les compteurs `api_rate_limits` sont des données opérationnelles pseudonymisées ; chaque document est réutilisé pour les fenêtres successives.

## Règles opérationnelles immédiates

1. Ne pas activer `ENABLE_DATASET_COLLECTION` tant qu'un écran de consentement, une procédure de retrait et une procédure de suppression des enregistrements concernés ne sont pas opérationnels.
2. Ne pas utiliser `global_datasets` pour l'entraînement avant revue des anciens enregistrements et validation de la provenance/du consentement.
3. Ne pas inscrire les prompts, réponses, jetons Firebase, clés fournisseurs, références de paiement ou données d'identité dans les journaux.
4. Les historiques cloud ne doivent être accessibles qu'au propriétaire authentifié ; les règles 401/403 de la Phase 2 protègent les routes HTTP.
5. La suppression locale ne doit pas être présentée comme une suppression cloud tant que la Phase 4 n'a pas finalisé la synchronisation des suppressions.

## Politique de conservation à approuver

La Phase 2 documente l'état des données et les barrières immédiates, mais ne fixe pas silencieusement de durée légale de conservation. Avant le lancement, CRYPT doit approuver des durées explicites pour :
- l'historique cloud et les suppressions demandées ;
- les sauvegardes Firestore ;
- les journaux techniques ;
- les compteurs de quotas ;
- les données d'amélioration collectées avec consentement.

La Phase 4 doit livrer l'export, la suppression synchronisée et les contrôles utilisateur correspondants. Une procédure d'effacement de compte doit également purger l'historique, les références de quotas et toute donnée liée à l'utilisateur lorsque cela est applicable.

## Statut

La collecte reste désactivée et les routes privées sont protégées. Les durées définitives et les suppressions cloud complètes restent des conditions avant lancement, à traiter avec la Phase 4 et une revue juridique adaptée.
