'''
NameBundle is an abstract Bundle supertype that all other bundle types subclass.
It requires name, description, and tags metadata for all of its subclasses.
TODO: merge into bundle.py.
'''
import time, re

from codalab.common import UsageError
from codalab.lib import spec_util
from codalab.objects.bundle import Bundle
from codalab.objects.metadata_spec import MetadataSpec


class NamedBundle(Bundle):
    NAME_LENGTH = 32

    METADATA_SPECS = (
      MetadataSpec('name', basestring, 'short variable name (not necessarily unique); must conform to ' + spec_util.NAME_REGEX.pattern, short_key='n'),
      MetadataSpec('description', basestring, 'full description of the bundle', short_key='d'),
      MetadataSpec('tags', list, 'space-separated list of tags used for search (e.g., machine-learning)', metavar='TAG'),
      MetadataSpec('created', int, 'time when this bundle was created', generated=True, formatting='date'),
      MetadataSpec('data_size', int, 'size of this bundle (in bytes)', generated=True, formatting='size'),
      MetadataSpec('failure_message', basestring, 'error message if bundle failed', generated=True),
    )

    @classmethod
    def construct(cls, row):
        # The base NamedBundle construct method takes a bundle row and adds in
        # automatically generated metadata values.
        row['metadata'] = dict(row['metadata'], created=int(time.time()))
        return cls(row)

    def validate(self):
        super(NamedBundle, self).validate()
        bundle_type = self.bundle_type.title()
        if not self.metadata.name:
            raise UsageError('%ss must have non-empty names' % (bundle_type,))
        spec_util.check_name(self.metadata.name)

    def __repr__(self):
        return '%s(uuid=%r, name=%r)' % (
          self.__class__.__name__,
          str(self.uuid),
          str(self.metadata.name),
        )

    def simple_str(self):
        return self.metadata.name + '(' + self.uuid + ')'
