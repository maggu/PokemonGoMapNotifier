from .utils import *
import logging

log = logging.getLogger(__name__)


class Handler:
    def __init__(self, config, notifier):
        self.config = config
        self.notifier = notifier

        self.processed_pokemons = {}
        self.processed_raids = {}
        self.processed_eggs = {}
        self.gyms = {}

    def clean(self):
        now = datetime.datetime.utcnow()
        remove = []

        for encounter_id in self.processed_pokemons:
            if self.processed_pokemons[encounter_id] < now:
                remove.append(encounter_id)
        for encounter_id in remove:
            del self.processed_pokemons[encounter_id]

        remove = []
        for key in self.processed_raids:
            if self.processed_raids[key] < now:
                remove.append(key)
        for key in remove:
            del self.processed_raids[key]

        remove = []
        for key in self.processed_eggs:
            if self.processed_eggs[key] < now:
                remove.append(key)
        for key in remove:
            del self.processed_eggs[key]

    def handle_pokemon(self, message):
        if message['encounter_id'] in self.processed_pokemons:
            log.debug('Encounter ID %s already processed.', message['encounter_id'])
            return

        self.processed_pokemons[message['encounter_id']] = \
            datetime.datetime.utcfromtimestamp(message['disappear_time'])

        # initialize the pokemon dict
        pokemon = {
            'id': message['pokemon_id'],
            'name': get_pokemon_name(message['pokemon_id']),
            'lat': message['latitude'],
            'lon': message['longitude']
        }

        if message.get('cp') is not None:
            pokemon['cp'] = message['cp']

        if message.get('pokemon_level') is not None:
            pokemon['level'] = message['pokemon_level']

        if message.get('form') is not None:
            pokemon['form'] = chr(message['form'] + 64)

        # calculate IV if available and add corresponding values to the pokemon dict
        attack = int(message.get('individual_attack') if message.get('individual_attack') is not None else -1)
        defense = int(message.get('individual_defense') if message.get('individual_defense') is not None else -1)
        stamina = int(message.get('individual_stamina') if message.get('individual_stamina') is not None else -1)
        if attack > -1 and defense > -1 and stamina > -1:
            iv = float((attack + defense + stamina) * 100 / float(45))
            pokemon['attack'] = attack
            pokemon['defense'] = defense
            pokemon['stamina'] = stamina
            pokemon['iv'] = iv

        # add moves to pokemon dict if found
        move_1, move_2 = None, None
        if message.get('move_1') is not None:
            move_1 = get_move_name(message['move_1'])
        if message.get('move_2') is not None:
            move_2 = get_move_name(message['move_2'])

        if move_1 is not None:
            pokemon['move_1'] = move_1
        if move_2 is not None:
            pokemon['move_2'] = move_2

        to_notify = set([])

        # Loop through all active includes and send notifications if appropriate
        for include_ref in self.config.pokemon_includes:
            include = self.config.pokemon_includes.get(include_ref)
            match = self.is_included_pokemon(pokemon, include)

            if match:
                notification_setting_refs = self.config.pokemon_includes_to_notifications.get(include_ref)

                if notification_setting_refs is not None:
                    for notification_setting_ref in notification_setting_refs:
                        to_notify.add(notification_setting_ref)
            else:
                log.debug('No match for %s in %s', pokemon['name'], include_ref)

        if to_notify:
            log.info('Notifying to %s', to_notify)
            for notification_setting_ref in to_notify:
                notification_setting = self.config.notification_settings.get(notification_setting_ref)
                self.notifier.notify_pokemon(pokemon, message, notification_setting)

    def handle_gym_details(self, message):
        parsed_gym = message['id']
        if parsed_gym not in self.gyms:
            # first scan of this gym
            self.gyms[parsed_gym] = {
                'name': message['name'],
                'lat': message['latitude'],
                'lon': message['longitude'],
                'team': message['team'],
                'pokemons': message['pokemon'],
                'trainers': [p['trainer_name'] for p in message['pokemon']]
            }

            # no further parsing. we only detect changes from here
            return

        gym = self.gyms[parsed_gym]
        trainers = [p['trainer_name'] for p in message['pokemon']]

        for notification_settings in self.config.notification_settings.itervalues():
            if not notification_settings.get('gym'):
                continue

            for tracked_trainer_name in self.config.trainers:

                if tracked_trainer_name in trainers:
                    # was he in the gym before?
                    trainer_existed = False
                    for trainer_name in gym.get('trainers', []):
                        if tracked_trainer_name == trainer_name:
                            # trainer is still in the gym
                            trainer_existed = True
                            break

                    if not trainer_existed:
                        # he wasn't in the gym before!
                        data = {
                            'trainer_name': tracked_trainer_name,
                            'name': gym['name'],
                            'lat': message['latitude'],
                            'lon': message['longitude'],
                            'team': message['team'],
                            'google_maps': get_google_maps(message['latitude'], message['longitude']),
                            'static_google_maps': get_static_google_maps(message['latitude'], message['longitude'],
                                                                         self.config.google_key)
                        }
                        log.info("%s joined gym: %s", tracked_trainer_name, gym['name'])
                        self.notifier.notify_gym(data, notification_settings)

        # finally update the gym for next time
        self.gyms[parsed_gym] = {
            'name': message['name'],
            'lat': message['latitude'],
            'lon': message['longitude'],
            'team': message['team'],
            'pokemons': message['pokemon'],
            'trainers': [p['trainer_name'] for p in message['pokemon']]
        }

    def handle_raid(self, message):
        egg = message['pokemon_id'] is None
        key = message['gym_id'] + str(message['start'])
        if egg:
            if key in self.processed_eggs:
                log.debug('Egg [%s] already processed.', key)
                return
            self.processed_eggs[key] = datetime.datetime.utcfromtimestamp(message['end'])
        else:
            if key in self.processed_raids:
                log.debug('Raid [%s] already processed.', key)
                return
            self.processed_raids[key] = datetime.datetime.utcfromtimestamp(message['end'])

        raid = {
            'lat': message['latitude'],
            'lon': message['longitude'],
            'level': message['level'],
            'gym_id': message['gym_id'],
            'gym': self.gyms.get(message['gym_id']),
            'spawn': message['spawn'],
            'start': message['start'],
            'end': message['end'],
            'egg': egg
        }

        if egg:
            raid['name'] = "Egg"
        else:
            raid['id'] = message['pokemon_id']
            raid['name'] = get_pokemon_name(message['pokemon_id'])
            raid['cp'] = message['cp']
            raid['move_1'] = get_move_name(message['move_1'])
            raid['move_2'] = get_move_name(message['move_2'])

        to_notify = set([])

        # Loop through all active includes and send notifications if appropriate
        for include_ref in self.config.raid_includes:
            include = self.config.raid_includes.get(include_ref)
            match = self.is_included_raid(raid, include)

            if match:
                notification_setting_refs = self.config.raid_includes_to_notifications.get(include_ref)

                if notification_setting_refs is not None:
                    for notification_setting_ref in notification_setting_refs:
                        to_notify.add(notification_setting_ref)
            else:
                log.debug('No match for %s in %s', raid['name'], include_ref)

        if to_notify:
            log.info('Notifying %s to %s', "egg" if egg else "raid", to_notify)
            for notification_setting_ref in to_notify:
                notification_setting = self.config.notification_settings.get(notification_setting_ref)
                self.notifier.notify_raid_or_egg(raid, notification_setting)

    def is_included_pokemon(self, pokemon, included_list):
        matched = False
        for included_pokemon in included_list:
            match = self.pokemon_matches(pokemon, included_pokemon)
            if match[0]:
                log.info(u"Found match for {} with rules: {}".format(pokemon['name'], match[1]))
                matched = True

        return matched

    def raid_matches(self, raid, rules):
        match_data = []

        egg = raid['egg']

        if egg and not rules.get('egg', True):
            return False, None

        if not egg and not rules.get('raid', True):
            return False, None

        levels = rules.get('levels')
        if levels is not None:
            if raid['level'] not in levels:
                return False, None

            match_data.append('levels')

        if 'geofence' in rules:
            if not self.is_inside_geofence(rules['geofence'], raid.get('lat'), raid.get('lon')):
                return False, None

            match_data.append('geofence')

        # only process pokemon rules if it's not an egg
        if not egg:
            pokemons = rules.get('pokemons', {})
            for pokemon_rules in pokemons:
                name = pokemon_rules.get('name')
                if name is not None:
                    if name != raid['name']:
                        return False, None
                    else:
                        match_data.append('name')

                # check cp at level
                min_cp = pokemon_rules.get('min_cp')
                if min_cp is not None:
                    if raid['cp'] < min_cp:
                        return False, None

                    match_data.append('min_cp')

                max_cp = pokemon_rules.get('max_cp')
                if max_cp is not None:
                    if raid['cp'] > max_cp:
                        return False, None

                    match_data.append('max_cp')

                if 'moves' in pokemon_rules:
                    moves = pokemon_rules['moves']
                    moves_match = False
                    for move_set in moves:
                        move_1 = move_set.get('move_1')
                        move_2 = move_set.get('move_2')
                        move_1_match = move_1 is None or move_1 == raid['move_1']
                        move_2_match = move_2 is None or move_2 == raid['move_2']
                        if move_1_match and move_2_match:
                            moves_match = True
                            break
                    if not moves_match:
                        return False, None

                    match_data.append('moves')

        return True, match_data

    def pokemon_matches(self, pokemon, pokemon_rules):
        match_data = []

        # check name. if name specification doesn't exist, it counts as valid
        name = pokemon_rules.get('name')
        if name is not None:
            if name != pokemon['name']:
                return False, None
            else:
                match_data.append('name')

        # check latitude
        if not Handler.check_min_max('lat', pokemon_rules, pokemon, match_data):
            return False, None

        # check longitude
        if not Handler.check_min_max('lon', pokemon_rules, pokemon, match_data):
            return False, None

        # check id
        if not Handler.check_min_max('id', pokemon_rules, pokemon, match_data):
            return False, None

        # check iv
        if not Handler.check_min_max('iv', pokemon_rules, pokemon, match_data):
            return False, None

        # check attack
        if not Handler.check_min_max('attack', pokemon_rules, pokemon, match_data):
            return False, None

        # check defense
        if not Handler.check_min_max('defense', pokemon_rules, pokemon, match_data):
            return False, None

        # check stamina
        if not Handler.check_min_max('stamina', pokemon_rules, pokemon, match_data):
            return False, None

        # check level (raids)
        if not Handler.check_min_max('level', pokemon_rules, pokemon, match_data):
            return False, None

        # check cp at level
        min_cp = pokemon_rules.get('min_cp')
        if min_cp is not None:
            if 'attack' not in pokemon or 'defense' not in pokemon or 'stamina' not in pokemon:
                return False, None

            for level in min_cp:
                required_cp = min_cp[level]
                cp = get_cp_for_level(pokemon['id'], int(level), pokemon['attack'], pokemon['defense'],
                                      pokemon['stamina'])
                if cp < required_cp:
                    return False, None

            match_data.append('min_cp')

        max_cp = pokemon_rules.get('max_cp')
        if max_cp is not None:
            if 'attack' not in pokemon or 'defense' not in pokemon or 'stamina' not in pokemon:
                return False, None

            for level in max_cp:
                required_cp = max_cp[level]
                cp = get_cp_for_level(pokemon['id'], level, pokemon['attack'], pokemon['defense'], pokemon['stamina'])
                if cp < required_cp:
                    return False, None

            match_data.append('max_cp')

        # check hp at level
        min_hp = pokemon_rules.get('min_hp')
        if min_hp is not None:
            if 'stamina' not in pokemon:
                return False, None

            for level in min_hp:
                required_hp = min_hp[level]
                hp = get_hp_for_level(pokemon['id'], int(level), pokemon['stamina'])
                if hp < required_hp:
                    return False, None

            match_data.append('min_hp')

        max_hp = pokemon_rules.get('max_hp')
        if max_hp is not None:
            if 'stamina' not in pokemon:
                return False, None

            for level in max_hp:
                required_hp = max_hp[level]
                hp = get_hp_for_level(pokemon['id'], level, pokemon['stamina'])
                if hp < required_hp:
                    return False, None

            match_data.append('max_hp')

        # check moves
        if 'moves' in pokemon_rules:
            moves = pokemon_rules['moves']
            moves_match = False
            for move_set in moves:
                move_1 = move_set.get('move_1')
                move_2 = move_set.get('move_2')
                move_1_match = move_1 is None or move_1 == pokemon.get('move_1')
                move_2_match = move_2 is None or move_2 == pokemon.get('move_2')
                if move_1_match and move_2_match:
                    moves_match = True
                    break
            if not moves_match:
                return False, None

            match_data.append('moves')

        if 'geofence' in pokemon_rules:
            if not self.is_inside_geofence(pokemon_rules['geofence'], pokemon.get('lat'), pokemon.get('lon')):
                return False, None

            match_data.append('geofence')

        # Passed all checks. This pokemon matches!
        return True, match_data

    @staticmethod
    def check_min(config_key, included_pokemon, message_key, pokemon, match_data):
        required_value = included_pokemon.get(config_key)
        if required_value is None:
            return True

        pokemon_value = pokemon.get(message_key, -1)
        if pokemon_value < required_value:
            return False

        match_data.append(config_key)
        return True

    @staticmethod
    def check_max(config_key, included_pokemon, message_key, pokemon, match_data):
        required_value = included_pokemon.get(config_key)
        if required_value is None:
            return True

        pokemon_value = pokemon.get(message_key, 99999)
        if pokemon_value > required_value:
            return False

        match_data.append(config_key)
        return True

    @staticmethod
    def check_min_max(key, included_pokemon, pokemon, match_data):
        """
        Returns True if included_pokemon matches the given pokemon
        """
        check_min = Handler.check_min('min_' + key, included_pokemon, key, pokemon, match_data)
        check_max = Handler.check_max('max_' + key, included_pokemon, key, pokemon, match_data)
        return check_min and check_max

    def is_included_raid(self, raid, included_list):
        match = self.raid_matches(raid, included_list)
        if match[0]:
            log.info(
                u"Found raid match for {} with rules: {}".format("Egg" if raid['egg'] else raid['name'], match[1]))
            return True

        return False

    def is_inside_geofence(self, geofence_name, lat, lon):
        geofence = self.config.geofences.get(geofence_name)
        if geofence is None:
            log.warning("geofence {} not found", geofence_name)
            return False

        # fast boundaries check
        boundaries = geofence['boundaries']
        min_x = boundaries['min'][0]
        min_y = boundaries['min'][1]
        max_x = boundaries['max'][0]
        max_y = boundaries['max'][1]

        if lat < min_x or lat > max_x or lon < min_y or lon > max_y:
            return False

        return is_inside_polygon(geofence['polygon'], lat, lon)
