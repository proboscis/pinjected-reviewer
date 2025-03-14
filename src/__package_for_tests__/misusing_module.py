from pinjected.test import injected_pytest
from __package_for_tests__.test_material import some_configuration


@injected_pytest()
def test(some_configuration):
    # This, is a correct usage but detected as misuse.
    # aha, because @injected_pytest is not treated as injection point.
    print(some_configuration)