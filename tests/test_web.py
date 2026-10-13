from jobagent.sources.web import looks_like_job

REAL = ("About the role\nYou will partner with the founders. Responsibilities include planning and reporting. "
        "Requirements: 4+ years of experience in strategy. Apply now. " * 5)


def test_real_job_accepted():
    assert looks_like_job("Chief of Staff", REAL)


def test_marketing_link_rejected():
    assert not looks_like_job("Playbooks Check out how 5000+ GTM teams win with Storylane", REAL)
    assert not looks_like_job("GTM", "Short marketing page about our product. Book a demo.")
