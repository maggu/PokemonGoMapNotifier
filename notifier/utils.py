import json
import datetime
import requests
import logging
import gpxpy.geo
import math

log = logging.getLogger(__name__)


def get_pokemon_name(id):
    if not hasattr(get_pokemon_name, 'names'):
        with open('data/names.json', 'r') as f:
            get_pokemon_name.names = json.load(f)

    return get_pokemon_name.names.get(str(id), 'unknown')


def get_move_name(id):
    if not hasattr(get_move_name, 'names'):
        with open('data/moves.json', 'r') as f:
            get_move_name.names = json.load(f)

    return get_move_name.names.get(str(id), 'unknown')


def get_time_left(disappear_time):
    tth = datetime.datetime.fromtimestamp(disappear_time) - datetime.datetime.now()
    seconds = tth.total_seconds()
    minutes, seconds = divmod(seconds, 60)

    return u"%02d:%02d" % (minutes, seconds)


def get_disappear_time(disappear_time):
    return datetime.datetime.fromtimestamp(disappear_time).strftime('%H:%M')


def get_google_maps(latitude, longitude):
    return "https://www.google.com/maps/place/{},{}".format(latitude, longitude)


def get_gamepress(pokemon_id):
    return "https://pokemongo.gamepress.gg/pokemon/{}".format(pokemon_id)


def get_static_google_maps(latitude, longitude, width=300, height=180, zoom=14):
    return "https://maps.googleapis.com/maps/api/staticmap?markers={},{}&zoom={}&size={}x{}".format(
        latitude,
        longitude, zoom, width, height)


def get_sublocality(latitude, longitude, api_key):
    if not api_key:
        return None

    base = "https://maps.googleapis.com/maps/api/geocode/json?"
    params = "latlng={lat},{lon}&sensor={sen}&key={api_key}".format(
        lat=latitude,
        lon=longitude,
        sen='true',
        api_key=api_key
    )
    url = "{base}{params}".format(base=base, params=params)
    try:
        response = requests.get(url)
    except requests.exceptions.RequestException as e:
        log.exception("Error fetching sublocality")
        return None

    if not response.ok:
        log.error("Error in response when fetching sublocality: %s", str(response))
        return None

    for result in response.json()['results']:
        if 'address_components' in result:
            address_components = result['address_components']

            for address in address_components:
                address_types = address['types']

                if 'sublocality' in address_types:
                    return address['long_name']

    return None


def get_distance(lat1, lon1, lat2, lon2):
    return int(gpxpy.geo.haversine_distance(lat1, lon1, lat2, lon2))


def get_stats(pokemon_id):
    if not hasattr(get_pokemon_name, 'stats'):
        with open('data/stats.json', 'r') as f:
            get_stats.stats = json.load(f)

    return get_stats.stats.get(str(pokemon_id))


def get_cpm_for_level(level):
    if not hasattr(get_cpm_for_level, 'cpm'):
        with open('data/cpm.json', 'r') as f:
            get_cpm_for_level.cpm = json.load(f)

    return get_cpm_for_level.cpm.get(str(level))


def get_cp_for_level(pokemon_id, level, iv_attack, iv_defense, iv_stamina):
    stats = get_stats(pokemon_id)
    attack = stats.get('attack') + iv_attack
    defense = stats.get('defense') + iv_defense
    stamina = stats.get('stamina') + iv_stamina

    cp_multiplier = get_cpm_for_level(level)

    cp = attack * math.sqrt(defense) * math.sqrt(stamina) * (math.pow(cp_multiplier, 2) / float(10))

    return int(math.floor(cp))


def get_hp_for_level(pokemon_id, level, iv_stamina):
    stats = get_stats(pokemon_id)
    stamina = stats.get('stamina') + iv_stamina

    cp_multiplier = get_cpm_for_level(level)

    hp = stamina * cp_multiplier

    return int(math.floor(hp))
