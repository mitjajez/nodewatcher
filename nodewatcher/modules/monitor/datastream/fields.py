import collections
import copy

from django.core import exceptions

from datastream import exceptions as ds_exceptions

from nodewatcher.utils import datastructures
from .pool import pool


class TagReference(object):
    """
    A reference to a tag that is dynamically generated by the streams
    descriptor in method get_stream_tags.
    """

    def __init__(self, tag_or_iterable=None, transform=None):
        """
        Class constructor.

        :param tag_or_iterable: Tag name or a list of referenced tags
        :param transform: String or callable to transform the tag; callable
                          gets the model instance as first argument
        """

        if tag_or_iterable is None:
            tag_or_iterable = []
        elif not isinstance(tag_or_iterable, (list, tuple)):
            tag_or_iterable = [tag_or_iterable]

        self.tags = tag_or_iterable
        self.transform = transform

    def resolve(self, descriptor):
        """
        Resolves this field reference into an actual value.

        :param descriptor: Streams descriptor
        :return: Value of the referenced field
        """

        # TODO: Dictionary comprehension in Python 2.7+
        tag_values = dict([
            (ref, reduce(lambda x, y: x[y], ref.split('.'), descriptor.get_stream_tags()))
            for ref in self.tags
        ])

        if callable(self.transform):
            return self.transform(descriptor.get_model(), **tag_values)
        elif isinstance(self.transform, basestring):
            return self.transform % tag_values
        elif len(tag_values) == 1:
            return tag_values.values()[0]
        else:
            raise ValueError("Multiple tags specified without transform callable!")


class Field(object):
    """
    A datastream Field contains metadata on how to extract datapoints and create
    streams from them. Values are then appended to these streams via the datastream
    API.
    """

    def __init__(self, attribute=None, tags=None, value_downsamplers=None, value_type='numeric'):
        """
        Class constructor.

        :param attribute: Optional name of the attribute that is source of data for
          this field
        :param tags: Optional custom tags
        :param value_downsamplers: Optional value downsamplers to use
        :param value_type: Optional datastream value type (defaults to numeric)
        """

        self.name = None
        self.attribute = attribute
        self.custom_tags = tags or {}
        self.default_tags = copy.deepcopy(self.custom_tags)

        if value_downsamplers is None:
            if value_type == 'numeric':
                value_downsamplers = [
                    'mean',
                    'sum',
                    'min',
                    'max',
                    'std_dev',
                    'count',
                ]
            elif value_type in ('graph', 'nominal'):
                value_downsamplers = [
                    'count',
                ]

        self.value_downsamplers = value_downsamplers
        self.value_type = value_type

    def prepare_value(self, value):
        """
        Performs value pre-processing before inserting it into the datastream.

        :param value: Raw value extracted from the datastream object
        :return: Processed value
        """

        return value

    def prepare_tags(self):
        """
        Returns a dictionary of tags that will be included in the final stream.
        """

        combined_tags = {
            'name': self.name,
        }
        combined_tags.update(self.custom_tags)
        return combined_tags

    def prepare_query_tags(self):
        """
        Returns a dict of tags that will be used to uniquely identify the final
        stream in addition to document-specific tags. This is usually a subset
        of tags returned by `prepare_tags`.
        """

        return {'name': self.name}

    def get_downsamplers(self):
        """
        Returns a list of downsamplers that will be used for the underlying stream.
        """

        return self.value_downsamplers

    def _process_tag_references(self, tags, descriptor):
        """
        Processes tags and resolves all tag references.

        :param tags: A dictionary of tags
        :param descriptor: Streams descriptor
        :return: Processed dictionary of tags
        """

        output = None
        if isinstance(tags, dict):
            output = {}
            for key, value in tags.iteritems():
                output[key] = self._process_tag_references(value, descriptor)
        elif isinstance(tags, list):
            output = []
            for value in tags:
                output.append(self._process_tag_references(value, descriptor))
        elif isinstance(tags, TagReference):
            output = tags.resolve(descriptor)
        else:
            output = tags

        return output

    def process_tags(self, descriptor):
        """
        Returns a tuple (query_tags, tags) to be used by ensure_stream.
        """

        query_tags = descriptor.get_stream_query_tags()
        query_tags.update(self.prepare_query_tags())
        tags = descriptor.get_stream_tags()
        datastructures.merge_dict(tags, self.prepare_tags())
        tags = self._process_tag_references(tags, descriptor)
        return query_tags, tags

    def ensure_stream(self, descriptor, stream):
        """
        Creates stream and returns its identifier.

        :param descriptor: Destination stream descriptor
        :param stream: Stream API instance
        :return: Stream identifier
        """

        query_tags, tags = self.process_tags(descriptor)
        downsamplers = self.get_downsamplers()
        highest_granularity = descriptor.get_stream_highest_granularity()

        return stream.ensure_stream(query_tags, tags, downsamplers, highest_granularity, value_type=self.value_type)

    def to_stream(self, descriptor, stream, timestamp=None):
        """
        Creates streams and inserts datapoints to the stream via the datastream API.

        :param descriptor: Destination stream descriptor
        :param stream: Stream API instance
        :param timestamp: Optional datapoint timestamp
        """

        attribute = self.name if self.attribute is None else self.attribute
        if callable(attribute):
            value = attribute(descriptor.get_model())
        else:
            value = getattr(descriptor.get_model(), attribute)

        stream_id = self.ensure_stream(descriptor, stream)
        if value is None:
            return

        value = self.prepare_value(value)
        stream.append(stream_id, value, timestamp=timestamp)

    def reset_tags_to_default(self, **tags):
        """
        Resets specific tags to their default values, specified at field
        definition time. In order to specify nested tags, use dictionaries.

        For example, if there are tags::

            {'visualization': {'initial_set': False, 'foo': 'bar'}}

        And you want to reset the ``initial_set`` tag, you may call this method
        as follows::

            field.reset_tags_to_default(visualization={'initial_set': True})

        :param **tags: Keyword arguments describing the tags to reset
        """

        def reset_tags(tags, current_tags, default_tags):
            for tag, value in tags.items():
                if isinstance(value, collections.Mapping):
                    # Value is a further mapping, we should descend. If there is nothing under
                    # defaults for this tag, then act as if the default is an empty dictionary.
                    # This is needed to remove existing values in case there is no default.
                    default_value = default_tags.get(tag, {})
                    if not isinstance(default_value, collections.Mapping):
                        continue

                    current_value = current_tags.setdefault(tag, {})
                    reset_tags(value, current_value, default_value)
                    if not current_value:
                        # If nothing has been added, remove the empty dictionary.
                        del current_tags[tag]
                elif value is True:
                    # A true value means that this tag should be reset from defaults (if any). If
                    # there are no defaults for this tag, then the tag will be removed.
                    if tag in default_tags:
                        current_tags[tag] = default_tags[tag]
                    else:
                        del current_tags[tag]
                else:
                    raise ValueError("Reset tag value should be either a dictionary or a boolean True.")

        reset_tags(tags, self.custom_tags, self.default_tags)

    def set_tags(self, **tags):
        """
        Sets custom tags on this field.

        :param **tags: Keyword arguments describing the tags to set
        """

        def update(d, u):
            for k, v in u.iteritems():
                if isinstance(v, collections.Mapping):
                    r = update(d.get(k, {}), v)
                    d[k] = r
                else:
                    d[k] = u[k]
            return d

        update(self.custom_tags, tags)


class IntegerField(Field):
    """
    An integer-typed datastream field.
    """

    def __init__(self, **kwargs):
        """
        Class constructor.
        """

        kwargs['value_type'] = 'numeric'
        super(IntegerField, self).__init__(**kwargs)

    def prepare_value(self, value):
        return int(value)

    def prepare_tags(self):
        tags = super(IntegerField, self).prepare_tags()
        tags.update({'type': 'integer'})
        return tags


class CounterField(IntegerField):
    """
    A counter field. This is basically an IntegerField but with certain
    value downsamplers disabled.
    """

    def __init__(self, **kwargs):
        """
        Class constructor.
        """

        kwargs.setdefault('value_downsamplers', [])
        tags = kwargs.setdefault('tags', {})
        visualization = tags.setdefault('visualization', {})
        visualization['initial_set'] = False

        super(CounterField, self).__init__(**kwargs)


class FloatField(Field):
    """
    A float-typed datastream field.
    """

    def __init__(self, **kwargs):
        """
        Class constructor.
        """

        kwargs['value_type'] = 'numeric'
        super(FloatField, self).__init__(**kwargs)

    def prepare_value(self, value):
        return float(value)

    def prepare_tags(self):
        tags = super(FloatField, self).prepare_tags()
        tags.update({'type': 'float'})
        return tags


class MultiPointField(Field):
    """
    A datastream field that accepts already downsampled datapoints which
    represent multiple actual datapoints.
    """

    def __init__(self, **kwargs):
        """
        Class constructor.
        """

        kwargs['value_type'] = 'numeric'
        super(MultiPointField, self).__init__(**kwargs)

    def prepare_value(self, value):
        return dict(value)

    def prepare_tags(self):
        tags = super(MultiPointField, self).prepare_tags()
        tags.update({'type': 'multipoint'})
        return tags


class DerivedField(Field):
    """
    A derived datastream field.
    """

    def __init__(self, streams, op, arguments=None, **kwargs):
        """
        Class constructor.

        :param streams: A list of input stream descriptors
        :param op: Operator name
        :param arguments: Optional operator arguments
        """

        self.streams = streams
        self.op = op
        self.op_arguments = arguments or {}

        super(DerivedField, self).__init__(**kwargs)

    def ensure_stream(self, descriptor, stream):
        """
        Creates stream and returns its identifier.

        :param descriptor: Destination stream descriptor
        :param stream: Stream API instance
        :return: Stream identifier
        """

        # Acquire references to input streams
        streams = []
        for field_ref in self.streams:
            model_reference, field = field_ref['field'].split('#')
            mdl = descriptor.get_model()
            if model_reference:
                mdl = descriptor.resolve_model_reference(model_reference)

            mdl_descriptor = pool.get_descriptor(mdl)
            field = mdl_descriptor.get_field(field)
            if field is None:
                raise exceptions.ImproperlyConfigured("Datastream field '%s' not found!" % field_ref['field'])

            streams.append(
                {'name': field_ref['name'], 'stream': field.ensure_stream(mdl_descriptor, stream)}
            )

        query_tags, tags = self.process_tags(descriptor)
        downsamplers = self.get_downsamplers()
        highest_granularity = descriptor.get_stream_highest_granularity()

        return stream.ensure_stream(
            query_tags,
            tags,
            downsamplers,
            highest_granularity,
            derive_from=streams,
            derive_op=self.op,
            derive_args=self.op_arguments,
            value_type=self.value_type,
        )

    def to_stream(self, descriptor, stream, timestamp=None):
        """
        Creates streams and inserts datapoints to the stream via the datastream API.

        :param descriptor: Destination stream descriptor
        :param stream: Stream API instance
        :param timestamp: Optional datapoint timestamp
        """

        self.ensure_stream(descriptor, stream)


class ResetField(DerivedField):
    """
    A field that generates a reset stream.
    """

    def __init__(self, field, **kwargs):
        """
        Class constructor.
        """

        kwargs['value_type'] = 'nominal'
        super(ResetField, self).__init__(
            [{'name': 'reset', 'field': field}],
            'counter_reset',
            **kwargs
        )


class RateField(DerivedField):
    """
    A rate datastream field.
    """

    def __init__(self, reset_field, data_field, max_value=None, **kwargs):
        """
        Class constructor.
        """

        kwargs['value_type'] = 'numeric'
        super(RateField, self).__init__(
            [
                {'name': 'reset', 'field': reset_field},
                {'name': None, 'field': data_field},
            ],
            'counter_derivative',
            arguments={
                'max_value': max_value,
            },
            **kwargs
        )


class DynamicSumField(Field):
    """
    A field that computes a sum of other source fields, the list of which
    can be dynamically modified. The underlying derived stream is automatically
    recreated whenever the set of source streams changes.
    """

    def __init__(self, **kwargs):
        """
        Class constructor.
        """

        self._fields = []
        kwargs['value_type'] = 'numeric'

        super(DynamicSumField, self).__init__(**kwargs)

    def clear_source_fields(self):
        """
        Clears all the source fields.
        """

        self._fields = []

    def add_source_field(self, field, descriptor):
        """
        Adds a source field.
        """

        self._fields.append((field, descriptor))

    def ensure_stream(self, descriptor, stream):
        """
        Creates stream and returns its identifier.

        :param descriptor: Destination stream descriptor
        :param stream: Stream API instance
        :return: Stream identifier
        """

        # Generate a list of input streams.
        streams = []
        for src_field, src_descriptor in self._fields:
            streams.append(
                {'stream': src_field.ensure_stream(src_descriptor, stream)}
            )

        if not streams:
            return

        query_tags, tags = self.process_tags(descriptor)
        downsamplers = self.get_downsamplers()
        highest_granularity = descriptor.get_stream_highest_granularity()

        try:
            return stream.ensure_stream(
                query_tags,
                tags,
                downsamplers,
                highest_granularity,
                derive_from=streams,
                derive_op='sum',
                derive_args={},
                value_type=self.value_type,
            )
        except ds_exceptions.InconsistentStreamConfiguration:
            # Drop the existing stream and re-create it.
            stream.delete_streams(query_tags)
            return stream.ensure_stream(
                query_tags,
                tags,
                downsamplers,
                highest_granularity,
                derive_from=streams,
                derive_op='sum',
                derive_args={},
                # Do not backprocess data as this could cause a lot of data to require processing,
                # which could greatly stall the monitoring process.
                derive_backprocess=False,
                value_type=self.value_type,
            )

    def to_stream(self, descriptor, stream, timestamp=None):
        """
        Creates streams and inserts datapoints to the stream via the datastream API.

        :param descriptor: Destination stream descriptor
        :param stream: Stream API instance
        :param timestamp: Optional datapoint timestamp
        """

        self.ensure_stream(descriptor, stream)


class GraphField(Field):
    """
    A field that can store graph datapoints.
    """

    def __init__(self, **kwargs):
        """
        Class constructor.
        """

        kwargs['value_type'] = 'graph'
        super(GraphField, self).__init__(**kwargs)

    def prepare_value(self, value):
        return dict(value)


class NominalField(Field):
    """
    A field that can contain any value but does not support any statistical
    operators.
    """

    def __init__(self, **kwargs):
        """
        Class constructor.
        """

        kwargs['value_type'] = 'nominal'
        super(NominalField, self).__init__(**kwargs)


class IntegerNominalField(NominalField):
    """
    A nominal field that contains integers.
    """

    def prepare_value(self, value):
        return int(value)


class IntegerArrayNominalField(NominalField):
    """
    A nominal field that contains an array of integers.
    """

    def prepare_value(self, value):
        return list([int(x) for x in value])
