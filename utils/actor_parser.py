from domain.movie import Actor
from domain.subtitle import BilingualText


def parse_actor_string(s: str):
    names = [
        name.strip()
        for name in s.replace("（", " ").replace("）", " ").replace("、", " ").split()
        if name.strip()
    ]
    return Actor(
        current_name=names[0],
        all_names=[BilingualText(original=name) for name in names],
    )
