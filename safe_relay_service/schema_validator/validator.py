import datetime
import json

from jsonschema import Draft4Validator, validate, validators
from jsonschema.exceptions import ValidationError

from safe_relay_service.utils.singleton import singleton


@singleton
class Validator(object):
    """JSON Schema Validator class"""

    def __init__(self, base_path='schemas'):
        if base_path[-1] != '/':
            base_path = base_path + '/'

        self._base_path = base_path
        self._schema = None
        self._custom_validator = None

    def load_schema(self, file_name):
        """Loads a JSON Schema
        Args:
            file_name: the JSON file name, along with its .json exstension
        Raises:
            IOError: if the file doesn't exists
            ValueError: if the json file isn't well formatted
        """
        if file_name[0] == '/':
            file_name = file_name[1:]

        with open(self._base_path + file_name) as f:
            self._schema = json.load(f)

    def extend_validator(self, name):
        """Sets a custom validator extending a Draft4Validator
        Args:
            name: the validator name
        Raises:
            Exception: if the validator doesn't exists for the given name
        """
        custom_validator = self.get_custom_validator(name)

        if not custom_validator:
            raise Exception('%s validator is not available' % name)
        else:
            new_validators = {name: custom_validator}
            self._custom_validator = validators.extend(Draft4Validator, new_validators)

    def get_custom_validator(self, name):
        """Returns a suitable jsonschema custom validator function
        Args:
            name: the validator name
        Returns:
            The custom validator function, None otherwise.
        """
        if name == 'date-time':
            def date_time_validator(validator, format, instance, schema):
                if not validator.is_type(instance, "string"):
                    return
                try:
                    datetime.datetime.strptime(instance, format)
                except ValueError as ve:
                    yield ValidationError(ve.message)

            return date_time_validator

        return None

    def validate(self, data):
        """Validates a dictionary against a schema
        Args:
            data: A dictionary
        Returns:
            Nothing for success, Exception otherwise.
        Raises:
            Exception: if schema is not provided
            jsonschema.exceptions.ValidationError: if data is cannot be validated
        """
        if not self._schema:
            raise Exception('Schema dictionary not provided')
        elif self._custom_validator:
            # Validate returns nothing
            self._custom_validator(self._schema).validate(data)
        else:
            # Validate returns nothing
            validate(data, self._schema)
