from threading import Thread
from .utils import *
import logging
import Queue
import json

log = logging.getLogger(__name__)


class Notifier(Thread):
    """
    Receives data from the webserver and deals with it.
    """

    def __init__(self):
        super(Notifier, self).__init__()

        self.daemon = True
        self.name = "Notifier"
        self.notification_handlers = {}

        self.queue = Queue.Queue()

        with open("config.json") as file:
            log.info("Loading config.json")
            parsed = json.load(file)

            log.info("Parsing \"config\"")
            config = parsed.get('config', {})
            self.google_key = config.get('google_key')
            self.fetch_sublocality = config.get('fetch_sublocality', False)
            self.shorten_urls = config.get('shorten_urls', False)

            log.info("Parsing \"endpoints\"")
            self.endpoints = parsed.get('endpoints', {})
            for endpoint in self.endpoints:
                endpoint_type = self.endpoints[endpoint].get('type', 'simple')
                if endpoint_type == 'simple' and 'simple' not in self.notification_handlers:
                    log.info("Adding Simple to available notification handlers")
                    from .simple import Simple
                    self.notification_handlers['simple'] = Simple()
                if endpoint_type == 'discord' and 'discord' not in self.notification_handlers:
                    log.info("Adding Discord to available notification handlers")
                    from .discord import Discord
                    self.notification_handlers['discord'] = Discord()

            log.info("Parsing \"includes\"")
            self.includes = parsed.get('includes', {})

            log.info("Parsing \"notification_settings\"")
            # filter out disabled notifiers
            self.notification_settings = [notification_setting for notification_setting in
                                          parsed.get('notification_settings', []) if
                                          notification_setting.get('config', {}).get('enabled', True)]

    def run(self):
        log.info("Notifier thread started.")

        while True:
            data = self.queue.get(block=True)

            message_type = data.get('type')

            if message_type == 'pokemon':
                self.handle_pokemon(data['message'])
            else:
                log.debug("Unsupported message type: %s" % message_type)

    @staticmethod
    def is_included_pokemon(pokemon, included_list):
        for included_pokemon in included_list:

            # check name. if name specification doesn't exist, it counts as valid
            name = included_pokemon.get('name')
            if name is not None and name != pokemon['name']:
                continue

            # check minimum iv
            min_iv = included_pokemon.get('min_iv')
            if min_iv is not None and pokemon.get('iv', -1) < min_iv:
                continue

            # check maximum iv
            max_iv = included_pokemon.get('max_iv')
            if max_iv is not None and pokemon.get('iv', 101) > max_iv:
                continue

            # check minimum cp
            min_cp = included_pokemon.get('min_cp')
            if min_cp is not None and pokemon.get('cp', -1) < min_cp:
                continue

            # check maximum cp
            max_cp = included_pokemon.get('max_cp')
            if max_cp is not None and pokemon.get('cp', 9999) > max_cp:
                continue

            # check moves
            if 'moves' in included_pokemon:
                moves = included_pokemon['moves']
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
                    continue

            # Passed all checks. This pokemon matches!
            log.debug("Found match for %s" % pokemon['name'])
            return True

        # Passed through all included pokemons but couldn't find a match
        log.debug("No match found for %s" % pokemon['name'])
        return False

    def handle_pokemon(self, message):
        log.debug("Handling pokemon message")

        # initialize the pokemon dict
        pokemon = {'name': get_pokemon_name(message['pokemon_id'])}

        # calculate IV if available and add corresponding values to the pokemon dict
        attack = int(message.get('individual_attack', -1))
        defense = int(message.get('individual_defense', -1))
        stamina = int(message.get('individual_stamina', -1))
        iv = float((attack + defense + stamina) * 100 / float(45))
        if iv >= 0:
            pokemon['attack'] = attack
            pokemon['defense'] = defense
            pokemon['stamina'] = stamina
            pokemon['iv'] = iv

        # add cp if available
        if 'cp' in message:
            pokemon['cp'] = int(message['cp'])

        # add moves to pokemon dict if found
        move_1 = get_move_name(message['move_1']) if 'move_1' in message else None
        move_2 = get_move_name(message['move_2']) if 'move_2' in message else None
        if move_1 is not None:
            pokemon['move_1'] = move_1
        if move_2 is not None:
            pokemon['move_2'] = move_2

        # loop through all notification settings and send notification if appropriate
        for notification_setting in self.notification_settings:
            if 'name' in notification_setting:
                log.debug("Checking through notification setting: %s" % notification_setting['name'])

            # check whether we should notify about this pokemon
            notify = False
            if 'includes' in notification_setting:
                include_refs = notification_setting['includes']
                for include_ref in include_refs:
                    include = self.includes.get(include_ref)
                    if include is None:
                        log.warn("Notification setting references unknown include: %s" % include_ref)
                        continue

                    notify = self.is_included_pokemon(pokemon, include)

            if notify:
                # find the handler and notify
                log.debug("Notifying about %s" % pokemon['name'])

                lat = message['latitude']
                lon = message['longitude']
                data = {
                    'id': message['pokemon_id'],
                    'encounter_id': message['encounter_id'],
                    'lat': message['latitude'],
                    'lon': message['longitude'],
                    'time': get_disappear_time(message['disappear_time']),
                    'time_left': get_time_left(message['disappear_time']),
                    'google_maps': get_google_maps(lat, lon, shorten=self.shorten_urls, api_key=self.google_key),
                    'static_google_maps': get_static_google_maps(lat, lon, shorten=self.shorten_urls,
                                                                 api_key=self.google_key),
                    'gamepress': get_gamepress(message['pokemon_id'], shorten=self.shorten_urls,
                                               api_key=self.google_key)
                }
                pokemon.update(data)

                # add sublocality
                if self.fetch_sublocality and self.google_key:
                    sublocality = get_sublocality(pokemon['lat'], pokemon['lon'], self.google_key)
                    if sublocality is not None:
                        pokemon['sublocality'] = sublocality

                # now notify all endpoints
                endpoints = notification_setting.get('endpoints', ['simple'])
                for endpoint_ref in endpoints:
                    endpoint = self.endpoints[endpoint_ref]
                    notification_type = endpoint.get('type', 'simple')
                    notification_handler = self.notification_handlers[notification_type]

                    log.info("Notifying to endpoint %s about %s" % (endpoint_ref, pokemon['name']))
                    notification_handler.notify_pokemon(endpoint, pokemon)
            else:
                # just debug log
                if log.isEnabledFor(logging.DEBUG):
                    if 'name' in notification_setting:
                        log.debug("Notification in %s for %s skipped" % (notification_setting['name'], pokemon['name']))
                    else:
                        log.debug("Notification for %s skipped" % pokemon['name'])

    def enqueue(self, data):
        self.queue.put(data)