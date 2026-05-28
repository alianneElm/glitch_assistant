"""Spotify playback control and search tools for Glitch."""

import logging
from typing import Optional

import httpx

from backend.services.spotify_auth import get_access_token, is_authenticated

logger = logging.getLogger(__name__)

API_BASE = "https://api.spotify.com/v1"


def _spotify_request(
    method: str,
    endpoint: str,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
) -> Optional[dict]:
    """Make an authenticated Spotify API request."""
    token = get_access_token()
    if not token:
        return None

    url = f"{API_BASE}{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}

    with httpx.Client(timeout=15) as client:
        resp = client.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json_body,
        )

        # 204 = success with no content (common for playback commands)
        if resp.status_code == 204:
            return {"status": "ok"}

        if resp.status_code == 404:
            return {"error": "no_device", "message": "No hay dispositivo activo. Abre Spotify en tu telefono o computadora."}

        if resp.status_code == 403:
            return {"error": "premium_required", "message": "Esta funcion requiere Spotify Premium."}

        resp.raise_for_status()

        if resp.content:
            return resp.json()
        return {"status": "ok"}


# --- Playback Control ---

def spotify_play(query: str = "", uri: str = "") -> str:
    """Play a song, album, playlist, or resume playback.

    Args:
        query: Search query to find and play (e.g. 'Bad Bunny', 'Despacito')
        uri: Direct Spotify URI (e.g. 'spotify:track:xxx'). Takes priority over query.
    """
    if not is_authenticated():
        return "Spotify no esta conectado. Pide a Alianne que visite /spotify/login para autorizar."

    try:
        body = {}

        if uri:
            # Direct URI
            if "track" in uri:
                body = {"uris": [uri]}
            else:
                body = {"context_uri": uri}
        elif query:
            # Search first, then play
            result = _spotify_request("GET", "/search", params={
                "q": query,
                "type": "track",
                "limit": 1,
            })
            if not result or not result.get("tracks", {}).get("items"):
                return f"No encontre '{query}' en Spotify."

            track = result["tracks"]["items"][0]
            track_name = track["name"]
            artist = track["artists"][0]["name"]
            body = {"uris": [track["uri"]]}

            resp = _spotify_request("PUT", "/me/player/play", json_body=body)
            if resp and resp.get("error") == "no_device":
                return resp["message"]
            return f"Reproduciendo: *{track_name}* de {artist}"

        # Resume playback (no query, no uri)
        resp = _spotify_request("PUT", "/me/player/play", json_body=body if body else None)
        if resp and resp.get("error") == "no_device":
            return resp["message"]
        return "Reproduccion reanudada"

    except Exception as e:
        logger.exception("Spotify play failed")
        return f"Error al reproducir: {e}"


def spotify_pause() -> str:
    """Pause playback."""
    if not is_authenticated():
        return "Spotify no esta conectado."

    try:
        resp = _spotify_request("PUT", "/me/player/pause")
        if resp and resp.get("error") == "no_device":
            return resp["message"]
        return "Musica pausada"
    except Exception as e:
        logger.exception("Spotify pause failed")
        return f"Error: {e}"


def spotify_next() -> str:
    """Skip to next track."""
    if not is_authenticated():
        return "Spotify no esta conectado."

    try:
        resp = _spotify_request("POST", "/me/player/next")
        if resp and resp.get("error") == "no_device":
            return resp["message"]

        # Get info about the new track
        current = _spotify_request("GET", "/me/player/currently-playing")
        if current and current.get("item"):
            name = current["item"]["name"]
            artist = current["item"]["artists"][0]["name"]
            return f"Siguiente: *{name}* de {artist}"
        return "Siguiente cancion"
    except Exception as e:
        logger.exception("Spotify next failed")
        return f"Error: {e}"


def spotify_previous() -> str:
    """Go to previous track."""
    if not is_authenticated():
        return "Spotify no esta conectado."

    try:
        resp = _spotify_request("POST", "/me/player/previous")
        if resp and resp.get("error") == "no_device":
            return resp["message"]

        current = _spotify_request("GET", "/me/player/currently-playing")
        if current and current.get("item"):
            name = current["item"]["name"]
            artist = current["item"]["artists"][0]["name"]
            return f"Anterior: *{name}* de {artist}"
        return "Cancion anterior"
    except Exception as e:
        logger.exception("Spotify previous failed")
        return f"Error: {e}"


def spotify_now_playing() -> str:
    """Get the currently playing track."""
    if not is_authenticated():
        return "Spotify no esta conectado."

    try:
        result = _spotify_request("GET", "/me/player/currently-playing")

        if not result or not result.get("item"):
            return "No hay nada sonando ahora."

        item = result["item"]
        name = item["name"]
        artist = ", ".join(a["name"] for a in item["artists"])
        album = item.get("album", {}).get("name", "")
        is_playing = result.get("is_playing", False)

        progress_ms = result.get("progress_ms", 0)
        duration_ms = item.get("duration_ms", 0)
        progress_min = progress_ms // 60000
        progress_sec = (progress_ms % 60000) // 1000
        duration_min = duration_ms // 60000
        duration_sec = (duration_ms % 60000) // 1000

        status = "Sonando" if is_playing else "Pausado"

        msg = f"{status}: *{name}* de {artist}"
        if album:
            msg += f"\nAlbum: {album}"
        msg += f"\n{progress_min}:{progress_sec:02d} / {duration_min}:{duration_sec:02d}"

        return msg

    except Exception as e:
        logger.exception("Spotify now playing failed")
        return f"Error: {e}"


def spotify_search(query: str, search_type: str = "track") -> str:
    """Search Spotify for tracks, artists, albums, or playlists.

    Args:
        query: Search query
        search_type: 'track', 'artist', 'album', or 'playlist'
    """
    if not is_authenticated():
        return "Spotify no esta conectado."

    try:
        result = _spotify_request("GET", "/search", params={
            "q": query,
            "type": search_type,
            "limit": 5,
        })

        if not result:
            return "Error al buscar en Spotify."

        key = f"{search_type}s"
        items = result.get(key, {}).get("items", [])

        if not items:
            return f"No encontre resultados para '{query}'."

        lines = [f"Resultados para '{query}':"]

        for i, item in enumerate(items, 1):
            if search_type == "track":
                artist = item["artists"][0]["name"]
                lines.append(f"{i}. *{item['name']}* — {artist}")
            elif search_type == "artist":
                followers = item.get("followers", {}).get("total", 0)
                lines.append(f"{i}. *{item['name']}* ({followers:,} seguidores)")
            elif search_type == "album":
                artist = item["artists"][0]["name"]
                year = item.get("release_date", "")[:4]
                lines.append(f"{i}. *{item['name']}* — {artist} ({year})")
            elif search_type == "playlist":
                owner = item.get("owner", {}).get("display_name", "?")
                total = item.get("tracks", {}).get("total", 0)
                lines.append(f"{i}. *{item['name']}* por {owner} ({total} canciones)")

        lines.append("\nDime el numero o nombre para reproducirlo.")
        return "\n".join(lines)

    except Exception as e:
        logger.exception("Spotify search failed")
        return f"Error al buscar: {e}"


def spotify_set_volume(volume: int) -> str:
    """Set playback volume (0-100).

    Args:
        volume: Volume level from 0 to 100
    """
    if not is_authenticated():
        return "Spotify no esta conectado."

    volume = max(0, min(100, volume))

    try:
        resp = _spotify_request("PUT", "/me/player/volume", params={"volume_percent": volume})
        if resp and resp.get("error") == "no_device":
            return resp["message"]
        return f"Volumen: {volume}%"
    except Exception as e:
        logger.exception("Spotify volume failed")
        return f"Error: {e}"


def spotify_queue(query: str) -> str:
    """Add a song to the queue.

    Args:
        query: Song name to search and add to queue
    """
    if not is_authenticated():
        return "Spotify no esta conectado."

    try:
        # Search for the track
        result = _spotify_request("GET", "/search", params={
            "q": query,
            "type": "track",
            "limit": 1,
        })

        if not result or not result.get("tracks", {}).get("items"):
            return f"No encontre '{query}' en Spotify."

        track = result["tracks"]["items"][0]
        track_uri = track["uri"]
        track_name = track["name"]
        artist = track["artists"][0]["name"]

        resp = _spotify_request("POST", "/me/player/queue", params={"uri": track_uri})
        if resp and resp.get("error") == "no_device":
            return resp["message"]

        return f"Agregado a la cola: *{track_name}* de {artist}"

    except Exception as e:
        logger.exception("Spotify queue failed")
        return f"Error: {e}"


def spotify_top(top_type: str = "tracks", time_range: str = "medium_term") -> str:
    """Get user's top tracks or artists.

    Args:
        top_type: 'tracks' or 'artists'
        time_range: 'short_term' (4 weeks), 'medium_term' (6 months), 'long_term' (all time)
    """
    if not is_authenticated():
        return "Spotify no esta conectado."

    try:
        result = _spotify_request("GET", f"/me/top/{top_type}", params={
            "time_range": time_range,
            "limit": 10,
        })

        if not result or not result.get("items"):
            return "No tengo suficientes datos para tu top todavia."

        period_labels = {
            "short_term": "ultimo mes",
            "medium_term": "ultimos 6 meses",
            "long_term": "de siempre",
        }
        period = period_labels.get(time_range, time_range)

        if top_type == "tracks":
            lines = [f"Tu top 10 canciones ({period}):"]
            for i, item in enumerate(result["items"], 1):
                artist = item["artists"][0]["name"]
                lines.append(f"{i}. *{item['name']}* — {artist}")
        else:
            lines = [f"Tu top 10 artistas ({period}):"]
            for i, item in enumerate(result["items"], 1):
                genres = ", ".join(item.get("genres", [])[:2]) or "sin genero"
                lines.append(f"{i}. *{item['name']}* ({genres})")

        return "\n".join(lines)

    except Exception as e:
        logger.exception("Spotify top failed")
        return f"Error: {e}"


def spotify_recommendations(mood: str = "", genre: str = "", based_on: str = "recent") -> str:
    """Get music recommendations based on mood, genre, or listening history.

    Args:
        mood: Mood/activity like 'relajado', 'fiesta', 'entrenar', 'estudiar', 'dormir'
        genre: Genre like 'reggaeton', 'rock', 'jazz', 'classical', 'pop'
        based_on: 'recent' (based on recent listens) or 'top' (based on top tracks)
    """
    if not is_authenticated():
        return "Spotify no esta conectado."

    try:
        # Map moods to Spotify audio features
        mood_params = {
            "relajado": {"max_energy": 0.4, "min_valence": 0.3, "max_tempo": 110},
            "relax": {"max_energy": 0.4, "min_valence": 0.3, "max_tempo": 110},
            "tranquilo": {"max_energy": 0.4, "min_valence": 0.3, "max_tempo": 110},
            "fiesta": {"min_energy": 0.7, "min_danceability": 0.7, "min_valence": 0.6},
            "party": {"min_energy": 0.7, "min_danceability": 0.7, "min_valence": 0.6},
            "entrenar": {"min_energy": 0.8, "min_tempo": 120},
            "gym": {"min_energy": 0.8, "min_tempo": 120},
            "workout": {"min_energy": 0.8, "min_tempo": 120},
            "correr": {"min_energy": 0.8, "min_tempo": 130},
            "estudiar": {"max_energy": 0.3, "max_valence": 0.5, "max_tempo": 100},
            "focus": {"max_energy": 0.3, "max_valence": 0.5, "max_tempo": 100},
            "dormir": {"max_energy": 0.2, "max_tempo": 80},
            "sleep": {"max_energy": 0.2, "max_tempo": 80},
            "triste": {"max_valence": 0.3, "max_energy": 0.4},
            "sad": {"max_valence": 0.3, "max_energy": 0.4},
            "feliz": {"min_valence": 0.7, "min_energy": 0.5},
            "happy": {"min_valence": 0.7, "min_energy": 0.5},
            "romantico": {"max_energy": 0.5, "min_valence": 0.4, "max_tempo": 120},
        }

        # Get seed tracks from recent or top
        if based_on == "top":
            seeds = _spotify_request("GET", "/me/top/tracks", params={
                "time_range": "medium_term",
                "limit": 5,
            })
        else:
            seeds = _spotify_request("GET", "/me/player/recently-played", params={
                "limit": 5,
            })

        seed_track_ids = []
        if seeds:
            if based_on == "top":
                items = seeds.get("items", [])
            else:
                items = [i["track"] for i in seeds.get("items", [])]
            seed_track_ids = [t["id"] for t in items[:5]]

        if not seed_track_ids:
            return "No tengo suficientes datos de escucha para recomendarte."

        # Build recommendation params
        params = {
            "seed_tracks": ",".join(seed_track_ids[:5]),
            "limit": 10,
        }

        # Add genre seed if provided
        if genre:
            params["seed_genres"] = genre.lower()
            # Reduce track seeds to make room (max 5 seeds total)
            params["seed_tracks"] = ",".join(seed_track_ids[:3])

        # Add mood audio features
        mood_key = mood.lower().strip()
        if mood_key in mood_params:
            params.update(mood_params[mood_key])

        result = _spotify_request("GET", "/recommendations", params=params)

        if not result or not result.get("tracks"):
            return "No encontre recomendaciones con esos criterios."

        # Build response
        label_parts = []
        if mood:
            label_parts.append(mood)
        if genre:
            label_parts.append(genre)
        label = " + ".join(label_parts) if label_parts else "para ti"

        lines = [f"Recomendaciones {label}:"]
        for i, track in enumerate(result["tracks"], 1):
            artist = track["artists"][0]["name"]
            lines.append(f"{i}. *{track['name']}* — {artist}")

        lines.append("\nDime un numero para reproducirlo o 'pon todas' para una cola.")
        return "\n".join(lines)

    except Exception as e:
        logger.exception("Spotify recommendations failed")
        return f"Error: {e}"
