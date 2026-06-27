def calculate_points(pred_home: int, pred_away: int, actual_home: int, actual_away: int) -> int:
    """
    10 pts: exact scoreline
     7 pts: correct outcome + correct goal difference
     5 pts: correct outcome only
     0 pts: wrong outcome
    """
    if pred_home == actual_home and pred_away == actual_away:
        return 10

    if _outcome(pred_home, pred_away) != _outcome(actual_home, actual_away):
        return 0

    if abs(pred_home - pred_away) == abs(actual_home - actual_away):
        return 7

    return 5


def _outcome(home: int, away: int) -> str:
    if home > away:
        return "H"
    if away > home:
        return "A"
    return "D"
