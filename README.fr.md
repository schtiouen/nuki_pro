<p align="center">
  <img src="https://raw.githubusercontent.com/schtiouen/nuki_pro/main/docs/nuki_logo_readme.png" alt="Nuki" width="220">
</p>

# Nuki Pro — intégration Home Assistant pour Nuki Smart Lock 5e génération

> Intégration communautaire non officielle, sans lien avec Nuki Home Solutions. Le nom et le logo Nuki sont des marques de Nuki Home Solutions GmbH ; ils servent uniquement à identifier les appareils pris en charge et ne sont pas couverts par la licence MIT.

[English version](README.md)

Intégration personnalisée pour la **Nuki Smart Lock Pro (5e génération)**, et plus largement les serrures Nuki de type 5 (Go, Pro, Ultra) et 3.0/4.0 Pro.
Elle donne accès à toutes les fonctions de la serrure, **sans Bridge** (non compatible avec la 5e génération) et **sans routeur Thread** :

- **Nuki Web API** (jeton, obligatoire) : état, réglages, utilisateurs, codes clavier, journal avec les noms ;
- **MQTT local** (facultatif, désactivé par défaut) : état instantané et actions sur votre réseau, avec bascule automatique sur la Web API.

## Entités

| Type | Entités |
| --- | --- |
| Serrure | Verrouiller, déverrouiller, ouvrir (gâche) ; états ouverte, en ouverture, bloquée ; `changed_by` = dernière personne |
| Capteurs | Batterie (%), État de la serrure, Mode, Sécurité de la porte, **Dernier utilisateur**, **Dernier déverrouillage par**, **Dernière ouverture par**, **Dernier verrouillage par**, Dernière action, Déclencheur, Heure de la dernière action, Firmware, État du serveur Nuki |
| Capteurs binaires | Verrouillée, Batterie critique, En charge, Mode nuit actif, Connexion MQTT, Connexion au serveur Nuki, Connexion Web API |
| Interrupteurs | Verrouillage automatique, Bouton activé, LED activée, Mises à jour automatiques, Vitesse lente en mode nuit, Appairage par le bouton, Cylindre désolidarisé, Poignée à relever, Détection auto du type de piles, **Accès « nom »** (un par utilisateur de l'app) |
| Listes | Bouton : appui simple / double appui, Vitesse du moteur, Délai Lock 'n' Go, Durée d'ouverture de la gâche, Mode Bluetooth, Type de piles |
| Nombre | Délai de verrouillage automatique |
| Boutons | Lock 'n' Go, Lock 'n' Go avec ouverture (désactivé par défaut), Verrouillage complet, Actualiser |
| Événement | **Activité** : chaque action avec la personne, le déclencheur et la source (code, empreinte), appuis « sans action » du bouton ou du fob, codes et empreintes refusés |

### Accessoires

Chaque accessoire appairé devient son propre appareil, relié à la serrure (« connecté via ») :

| Appareil | Entités |
| --- | --- |
| **Capteur de porte** (Door Sensor) | Porte ouverte/fermée, État (fermée, ouverte, calibrage, retiré…), Batterie critique, Sabotage, **Événements** : porte ouverte, porte fermée, porte restée ouverte, état incohérent, capteur bloqué |
| **Clavier** (Keypad / Keypad 2) | Batterie critique, Sabotage et Montage (antivol du Keypad 2), un interrupteur **Accès** par code clavier (nombre d'empreintes en attribut) |
| **Fob** | Action à 1, 2 et 3 appuis, interrupteur **Accès** du fob |

« Sécurité de la porte » (fermée et verrouillée, fermée non verrouillée, ouverte) reste sur la serrure car elle combine les deux. Un accessoire n'apparaît que s'il est appairé ; s'il est ajouté plus tard, ses entités sont créées sans redémarrage.

Les réglages peu courants sont créés désactivés : activez-les depuis la page de l'appareil.

Les attributs des capteurs « Dernier … » donnent l'action, le déclencheur, la source et l'horodatage. Les codes clavier ne sont jamais exposés.

## Prérequis

1. **Jeton Nuki Web API** : sur [web.nuki.io](https://web.nuki.io), menu **API**, générez un jeton en cochant les droits pour voir et gérer les serrures, les actionner, gérer les autorisations et la configuration, et voir le journal d'activité. Nuki Web doit être activé pour la serrure dans l'app.
2. **MQTT (facultatif)** : dans l'app Nuki, réglages de la serrure, *Fonctionnalités et configuration* > *Smart Home* > *MQTT* :
   - adresse du broker (Mosquitto), identifiant et mot de passe (32 caractères au plus) ; Nuki impose le port 1883 sans TLS, sur le réseau local ;
   - **désactivez la « Découverte automatique » (Auto discovery)**, sinon la serrure crée des entités en double dans l'intégration MQTT ;
   - laissez **« Autoriser le verrouillage »** activé pour les actions locales.

## Installation

### Par HACS (recommandé)

1. HACS > menu ⋮ > **Dépôts personnalisés** : URL `https://github.com/schtiouen/nuki_pro`, catégorie **Intégration**.
2. Cherchez **Nuki Pro** dans HACS, téléchargez-le, puis redémarrez Home Assistant.

HACS signale ensuite les nouvelles versions (releases GitHub).

### Par copie

Copiez le dossier `custom_components/nuki_pro` dans le dossier `custom_components` de votre configuration Home Assistant (module complémentaire Samba, SSH ou Studio Code Server), pour obtenir `/config/custom_components/nuki_pro/`. Redémarrez Home Assistant.

### Ajout de la serrure

**Paramètres > Appareils et services > Ajouter une intégration > Nuki Pro**, collez le jeton, puis choisissez d'utiliser le MQTT ou non. Si le MQTT de la serrure est actif, Home Assistant propose aussi la serrure dans « Découverts ».

Si vous utilisiez une autre intégration Nuki, supprimez-la et révoquez son jeton sur web.nuki.io.

### Options

| Option | Par défaut | Effet |
| --- | --- | --- |
| Intervalle d'interrogation de la Web API | Vide = automatique : 30 s, ou 300 s quand le MQTT est actif | 15 à 3600 s (limite Nuki : 1000 requêtes/h) |
| Canal des actions | Automatique | MQTT si joignable, sinon Web API ; ou forcer l'un des deux |
| Un interrupteur par utilisateur ou code | Oui | Désactivable si vous avez beaucoup de codes |

## Langues

L'interface existe en **français**, **anglais**, **allemand**, **espagnol**, **néerlandais** et **italien**. Les formulaires, états, actions et messages d'erreur suivent la langue de chaque utilisateur ; les noms des entités et des appareils sont créés dans la langue du système au moment de l'ajout de l'intégration. Les autres langues retombent sur l'anglais. Les nouvelles traductions sont les bienvenues dans `custom_components/nuki_pro/translations/` (`tests/test_translations.py` vérifie que chaque fichier a les mêmes clés et paramètres que `en.json`).

## Services

Tous ciblent l'entité serrure.

```yaml
# Verrouillage complet (double tour)
action: nuki_pro.lock_action
target:
  entity_id: lock.porte_d_entree
data:
  action: full_lock          # unlock, lock, unlatch, lock_n_go, lock_n_go_unlatch, full_lock
  transport: web             # facultatif : auto, mqtt, web

# Code clavier valable le lundi et le vendredi de 9 h à 12 h 30
action: nuki_pro.create_keypad_code
target:
  entity_id: lock.porte_d_entree
data:
  name: Livreur
  code: "456789"             # 6 chiffres de 1 à 9, ne commençant pas par 12
  allowed_weekdays: [mon, fri]
  allowed_from_time: "09:00"
  allowed_until_time: "12:30"

# Désactiver un accès (nom ou identifiant)
action: nuki_pro.update_authorization
target:
  entity_id: lock.porte_d_entree
data:
  authorization: Livreur
  enabled: false

# Supprimer un accès
action: nuki_pro.delete_authorization
target:
  entity_id: lock.porte_d_entree
data:
  authorization: Livreur
```

`nuki_pro.get_authorizations` et `nuki_pro.get_logs` (`limit` de 1 à 50) renvoient une réponse utilisable dans un script (`response_variable`).

## Automatisations

L'entité **Activité** se déclenche à chaque action. Exemple : notification quand quelqu'un ouvre avec un code clavier.

```yaml
triggers:
  - trigger: state
    entity_id: event.porte_d_entree_activite
conditions:
  - condition: template
    value_template: >
      {{ trigger.to_state.attributes.event_type in ['unlock', 'unlatch']
         and trigger.to_state.attributes.source == 'keypad_code' }}
actions:
  - action: notify.notify
    data:
      message: "Porte ouverte par {{ trigger.to_state.attributes.user }}"
```

Types d'événement de l'entité **Activité** : `unlock`, `lock`, `unlatch`, `lock_n_go`, `lock_n_go_unlatch`, `full_lock`, `button_no_action`, `fob_no_action`, `wrong_code`, `wrong_fingerprint`.

Types d'événement de l'entité **Événements** du capteur de porte : `door_opened`, `door_closed`, `door_ajar_warning` (porte restée ouverte), `door_status_mismatch`, `door_sensor_jammed`.

Astuce : réglez dans l'app Nuki une action de bouton (ou de fob) sur « aucune action ». Avec le MQTT, chaque appui déclenche alors `button_no_action` (ou `fob_no_action`) avec l'attribut `presses`, utilisable comme bouton d'automatisation.

Les identifiants d'entité dépendent du nom de la serrure et de la langue de Home Assistant : vérifiez-les sur la page de l'appareil.

## Fonctionnement

- Avec le MQTT, l'état arrive instantanément et ses valeurs priment ; la Web API est interrogée toutes les 5 min pour les réglages, les accès et le journal, et juste après chaque activité pour récupérer le nom de la personne.
- Sans MQTT, la Web API est interrogée toutes les 30 s : état, réglages et journal (2 requêtes par cycle, environ 250 par heure pour une limite de 1000) ; accès relus toutes les 15 min et après chaque changement.
- Si le MQTT tombe (serrure hors ligne, broker arrêté), la Web API prend le relais, à 30 s, sans rendre les entités indisponibles. Une action MQTT sans réponse est renvoyée par la Web API ; elle ne peut pas s'exécuter en retard (expiration de 10 s en MQTT 5, QoS 0 en MQTT 3.1.1).
- Si le jeton est révoqué alors que le MQTT fonctionne, la serrure reste utilisable en local et Home Assistant demande un nouveau jeton.
- Les changements de réglages s'affichent tout de suite, puis sont confirmés à la lecture suivante.
- Les accès modifiés dans l'app ne remontent sur Nuki Web qu'une fois par jour : le bouton **Actualiser** demande une synchronisation.

## Dépannage

- **Diagnostics** : page de l'appareil > ⋮ > *Télécharger les diagnostics* (jeton, codes, noms et GPS masqués).
- **Journaux détaillés** :

  ```yaml
  logger:
    logs:
      custom_components.nuki_pro: debug
  ```

- **« Rien reçu sur ce topic »** : vérifiez le MQTT dans l'app Nuki et le topic `nuki/<NUKI_ID>` avec MQTT Explorer, ou décochez MQTT.
- **Connexion MQTT qui clignote** : défaut connu du firmware 5.9.4 en Wi-Fi ; l'intégration bascule sur la Web API en attendant.

## Développement

```bash
uv venv -p 3.14 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/python -m pytest tests/
```

36 tests couvrent le mode Web API seule, le mode MQTT, les accessoires, l'assistant de configuration, les diagnostics, le logo et les traductions (Home Assistant 2026.10.4). Ils tournent aussi dans GitHub Actions, avec les validations hassfest et HACS.

Sources : [spécification Web API](https://api.nuki.io/static/swagger/swagger.json), [spécification MQTT v1.6](https://developer.nuki.io/t/about-the-mqtt-category/14233), [documentation Nuki](https://docs.nuki.io/guide/).

## Licence

Code sous licence [MIT](LICENSE) © 2026 msaid_dev. Le logo Nuki (dossier `brand/`) reste la propriété de Nuki Home Solutions GmbH.
