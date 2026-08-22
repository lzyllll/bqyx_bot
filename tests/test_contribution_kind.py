from bqyx_bot.models import ContributionKind


def test_contribution_kind_defaults():
    assert ContributionKind.DAILY.label == "今日贡献"
    assert ContributionKind.WEEKLY.label == "本周贡献"
    assert ContributionKind.DAILY.default_limit == 1100
    assert ContributionKind.WEEKLY.default_limit == 7700
