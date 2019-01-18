import os

from django.test import TestCase

from jsonschema.exceptions import ValidationError

from safe_relay_service.schema_validator.validator import Validator


class TestValidator(TestCase):
    def setUp(self):
        self.dirpath = os.path.dirname(__file__) + '/data'

    def test_validator_works(self):
        valid_data = {
            "type": "safeCreation",
            "params": {
                "safe": "0x0",
                "deployer": "0x0"
            }
        }

        invalid_data = {
            "params": {
                "safe": "0x0",
                "deployer": "0x0"
            }
        }
        validator = Validator(base_path=self.dirpath)
        validator.load_schema('test_schema.json')

        # Checks
        # .validate() returns nothing or raises a ValidationError
        is_valid = validator.validate(valid_data)
        self.assertIsNone(is_valid)
        with self.assertRaises(ValidationError):
            validator.validate(invalid_data)

    def test_schema_not_found(self):
        validator = Validator(base_path=self.dirpath + '/')
        with self.assertRaises(FileNotFoundError):
            validator.load_schema('not_existing_schema.json')
