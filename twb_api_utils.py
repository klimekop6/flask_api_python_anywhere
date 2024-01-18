def get_villages(lines: list[str]) -> list[str]:
    villages = []
    for line in lines:
        _, _, x, y, _, _, _ = line.split(",")
        villages.append(x + "|" + y)
    return villages


def get_villages_per_player_id(lines: list[str]) -> dict[str, list[str]]:
    villages_per_player_id = {}
    for line in lines:
        _, _, x, y, player_id, _, _ = line.split(",")
        if player_id in villages_per_player_id:
            villages_per_player_id[player_id].append(f"{x}|{y}")
        else:
            villages_per_player_id[player_id] = [f"{x}|{y}"]
    return villages_per_player_id


def get_players(players_list: list[str]) -> dict[str, str]:
    players = {}
    for player in players_list:
        player_id, _, player_tribe_id, _, _, _ = player.split(",")
        players[player_id] = player_tribe_id
    return players


def get_tribe_players_id(tribe_id: str, players: dict[str, str]) -> list[str]:
    tribe_players_id = []
    for player_id, player_tribe_id in players.items():
        if tribe_id == player_tribe_id:
            tribe_players_id.append(player_id)
    return tribe_players_id


def get_tribe_villages(
    tribe_players_id: list[str], villages_per_player_id: dict[str, list[str]]
) -> list[str]:
    tribe_villages = []
    for player_id in tribe_players_id:
        tribe_villages.extend(villages_per_player_id[player_id])

    return tribe_villages


def get_nearest_villages_to_the_target_sorted_by_distance(
    target_village: str, villages: list[str], top: int = 5
) -> list[str]:
    target_x, target_y = int(target_village[:3]), int(target_village[4:])
    return sorted(
        villages,
        key=lambda village: pow(target_x - int(village[:3]), 2)
        + pow(target_y - int(village[4:]), 2),
    )[:top]
