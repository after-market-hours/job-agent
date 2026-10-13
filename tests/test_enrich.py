import pytest

from jobagent.enrich import comp, equity, experience, visa


@pytest.mark.parametrize("text", [
    "We are unable to sponsor visas at this time.",
    "Applicants must be authorized to work in the US. We will not sponsor employment visas.",
    "No visa sponsorship is available for this role.",
    "This position does not offer visa sponsorship.",
    "We do not provide sponsorship for this role.",
    "Candidates must not require sponsorship now or in the future.",
    "Sponsorship is not available.",
])
def test_visa_refusals_excluded(text):
    assert visa(text)[0] == "excluded"


@pytest.mark.parametrize("text", [
    "Visa sponsorship is available for the right candidate.",
    "We will sponsor H-1B visas.",
    "We are happy to sponsor work visas.",
])
def test_visa_sponsors(text):
    assert visa(text)[0] == "sponsors"


def test_visa_auth_only():
    assert visa("You must be legally authorized to work in the United States.")[0] == "auth_required"


def test_visa_none():
    assert visa("We love tacos.") == ("none", "")


@pytest.mark.parametrize("text,line,excl", [
    ("6+ years of experience in strategy", "Exp: 6+ yrs", True),
    ("At least 7 years of experience", "Exp: 7+ yrs", True),
    ("8 years of relevant experience", "Exp: 8+ yrs", True),
    ("4-6 years of experience", "Exp: 4–6 yrs", False),
    ("5 to 8 years experience", "Exp: 5–8 yrs", False),
    ("3+ years of experience", "Exp: 3+ yrs", False),
    ("No requirement.", "Exp: not stated", False),
    ("6-8 years experience, 6+ years in ops", "Exp: 6–8 yrs", False),
])
def test_experience(text, line, excl):
    assert experience(text) == (line, excl)


def test_comp_structured_and_regex():
    assert comp("$211.4K – $290.6K • Offers Equity", "") == "$211.4K – $290.6K"
    assert comp("", "Range: $120,000 - $150,000 per year") == "$120,000 - $150,000"
    assert comp("", "nothing") == "Salary not listed"
    assert comp("€49,901 – €54,775 • 0.001% – 0.004%", "").startswith("€49,901")


def test_equity():
    assert equity("$1 – $2 • Offers Equity", "") == "Offers equity"
    assert equity("", "We value diversity, equity and inclusion.") == "Equity not stated"
    assert equity("", "Compensation includes stock options.") == "Equity mentioned"
    assert equity("", "Equity of 0.1% - 0.25% vesting over four years.").startswith("Equity: 0.1%")


def test_form_question_is_not_a_sponsorship_statement():
    assert visa("Will you require visa sponsorship now or in the future? *YesNo")[0] == "none"
    assert visa("Do you now or in the future require sponsorship to work in the US?")[0] == "none"
    assert visa("Visa sponsorship: Will sponsor")[0] == "sponsors"
