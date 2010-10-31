from django.conf import settings
from django.db import models
from django.db.models import signals
from django.utils.encoding import smart_unicode, smart_str

import pytz

from timezones import zones
from timezones.utils import coerce_timezone_value, validate_timezone_max_length, get_timezone



MAX_TIMEZONE_LENGTH = getattr(settings, "MAX_TIMEZONE_LENGTH", 100)
default_tz = pytz.timezone(getattr(settings, "TIME_ZONE", "UTC"))
INTERNAL_TZ = get_timezone(getattr(settings, 'TIMEZONES_INTERNAL_TZ', pytz.utc))





class TimeZoneField(models.CharField):
    
    __metaclass__ = models.SubfieldBase
    
    def __init__(self, *args, **kwargs):
        validate_timezone_max_length(MAX_TIMEZONE_LENGTH, zones.ALL_TIMEZONE_CHOICES)
        defaults = {
            "max_length": MAX_TIMEZONE_LENGTH,
            "default": settings.TIME_ZONE,
            "choices": zones.PRETTY_TIMEZONE_CHOICES
        }
        defaults.update(kwargs)
        return super(TimeZoneField, self).__init__(*args, **defaults)
    
    def validate(self, value, model_instance):
        # coerce value back to a string to validate correctly
        return super(TimeZoneField, self).validate(smart_str(value), model_instance)
    
    def run_validators(self, value):
        # coerce value back to a string to validate correctly
        return super(TimeZoneField, self).run_validators(smart_str(value))
    
    def to_python(self, value):
        value = super(TimeZoneField, self).to_python(value)
        if value is None:
            return None # null=True
        return coerce_timezone_value(value)
    
    def get_prep_value(self, value):
        if value is not None:
            return smart_unicode(value)
        return value
    
    def get_db_prep_save(self, value, connection=None):
        """
        Prepares the given value for insertion into the database.
        """
        return self.get_prep_value(value)
    
    def flatten_data(self, follow, obj=None):
        value = self._get_val_from_obj(obj)
        if value is None:
            value = ""
        return {self.attname: smart_unicode(value)}


class LocalizedDateTimeField(models.DateTimeField):
    """
    A model field that provides automatic localized timezone support.
    timezone can be a timezone string, a callable (returning a timezone string),
    or a queryset keyword relation for the model, or a pytz.timezone()
    result.
    """


    def __init__(self, verbose_name=None, name=None, timezone=None, save_timezone=True, **kwargs):
        if isinstance(timezone, basestring):
            timezone = smart_str(timezone)
        if timezone in pytz.all_timezones_set:
            self.timezone = pytz.timezone(timezone)
        else:
            self.timezone = timezone

        self.save_timezone = save_timezone

        super(LocalizedDateTimeField, self).__init__(verbose_name, name, **kwargs)


    def get_timezone_for_instance(self, instance):
        timezoneish = self.timezone

        # 1. Callable?
        if callable(timezoneish):
            timezoneish = timezoneish(instance)

        # 2. Attribute?
        if isinstance(timezoneish, basestring) and hasattr(instance, timezoneish):
            timezoneish = getattr(instance, timezoneish)

            # Callable (i.e. object method) ?
            if callable(timezoneish):
                timezoneish = timezoneish()

        # 3. At this point, timezoneish should be a string or a tzinfo-object
        return get_timezone(timezoneish, default_tz)
        
    def get_db_prep_save(self, value):
        """
        Returns field's value prepared for saving into a database.
        """
        if value is not None:
            if value.tzinfo is None:
                value = INTERNAL_TZ.localize(value)
            else:
                value = value.astimezone(INTERNAL_TZ)

            if not self.save_timezone:
                value = value.replace(tzinfo=None)

        return super(LocalizedDateTimeField, self).get_db_prep_save(value)

    def get_db_prep_lookup(self, lookup_type, value):
        """
        Returns field's value prepared for database lookup.
        """

        # Check for tzinfo-attribute. For certain lookup_types is not a datetime-like object
        # localizeddatetimefield__isnull=True will result in foo.get_db_prep_lookup('isnull', True)
        if hasattr(value, 'tzinfo'):
            ## convert to settings.TIME_ZONE
            if value.tzinfo is None:
                value = default_tz.localize(value)
            else:
                value = value.astimezone(default_tz)

        if not self.save_timezone:
            value = value.replace(tzinfo=None)

        return super(LocalizedDateTimeField, self).get_db_prep_lookup(lookup_type, value)

# This code could almost live in the loop directly
# The field loop variable will not be persistent in the created closures, and will 
# take the value of the last field in the loop, instead of the current field
# By passing field to another function, the proper field will be referenced in the
# getters/setters
def create_property(field):
    dt_field_name = "_dtz_%s" % field.attname

    def get_dtz_field(instance):
        return getattr(instance, dt_field_name)

    def set_dtz_field(instance, dt):

        if dt is None:
            setattr(instance, dt_field_name, None)
        else:
            if dt.tzinfo is None:
                dt = INTERNAL_TZ.localize(dt)

            timezone = field.get_timezone_for_instance(instance)
            setattr(instance, dt_field_name, dt.astimezone(timezone))

    return property(get_dtz_field, set_dtz_field)


def prep_localized_datetime(sender, **kwargs):
    for field in sender._meta.fields:
        if not isinstance(field, LocalizedDateTimeField) or field.timezone is None:
            continue

        setattr(sender, field.attname, create_property(field))

## RED_FLAG: need to add a check at manage.py validation time that
##           time_zone value is a valid query keyword (if it is one)
signals.class_prepared.connect(prep_localized_datetime)


try:
    from south.modelsinspector import add_introspection_rules

    add_introspection_rules(rules=[(
                                (LocalizedDateTimeField, ), 
                                    [], 
                                    {
                                        'timezone': ('timezone', {}),
                                        'save_timezone': ('save_timezone', {})
                                    })],
                                patterns=['timezones\.fields\.'])

except ImportError:
    pass
