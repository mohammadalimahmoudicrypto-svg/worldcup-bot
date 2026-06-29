def calculate_points(pred_home: int, pred_away: int, actual_home: int, actual_away: int, pred_winner: int = None, actual_winner: int = None) -> int:
    """
    10 pts: exact scoreline
     7 pts: correct outcome + correct goal difference
     5 pts: correct outcome only
     0 pts: wrong outcome
    +3 pts: correct winner after draw (penalty/extra time)
    """
    base = 0

    if pred_home == actual_home and pred_away == actual_away:
        base = 10
    elif _outcome(pred_home, pred_away) != _outcome(actual_home, actual_away):
        base = 0
    elif abs(pred_home - pred_away) == abs(actual_home - actual_away):
        base = 7
    else:
        base = 5

    # bonus for correct winner after draw
    if actual_home == actual_away and pred_winner is not None and actual_winner is not None:
        if pred_winner == actual_winner:
            base += 3

    return base

def _outcome(home: int, away: int) -> str:
    if home > away:
        return "H"
    if away > home:
        return "A"
    return "D"
