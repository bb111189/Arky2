"""
Created on June 10, 2012
@author: peta15
"""

from wtforms import fields
from wtforms import Form
from wtforms import validators
from lib import utils
from webapp2_extras.i18n import lazy_gettext as _
from webapp2_extras.i18n import ngettext, gettext

FIELD_MAXLENGTH = 50 # intended to stop maliciously long input


class FormTranslations(object):
    def gettext(self, string):
        return gettext(string)

    def ngettext(self, singular, plural, n):
        return ngettext(singular, plural, n)


class BaseForm(Form):
    
    def __init__(self, request_handler):
        super(BaseForm, self).__init__(request_handler.request.POST)
    def _get_translations(self):
        return FormTranslations()


class CurrentPasswordMixin(BaseForm):
    current_password = fields.TextField(_('Password'), [validators.Required(), validators.Length(max=FIELD_MAXLENGTH)])


class PasswordMixin(BaseForm):
    password = fields.TextField(_('Password'), [validators.Required(), validators.Length(max=FIELD_MAXLENGTH)])


class ConfirmPasswordMixin(BaseForm):
    c_password = fields.TextField(_('Confirm Password'), [validators.Required(), validators.EqualTo('password', _('Passwords must match.')), validators.Length(max=FIELD_MAXLENGTH)])


class UserMixin(BaseForm):
    username = fields.TextField(_('Username'), [validators.Required(), validators.Length(max=FIELD_MAXLENGTH), validators.regexp(utils.ALPHANUMERIC_REGEXP, message=_('Username invalid. Use only letters and numbers.'))])
    name = fields.TextField(_('Name'), [validators.Length(max=FIELD_MAXLENGTH)])
    last_name = fields.TextField(_('Last Name'), [validators.Length(max=FIELD_MAXLENGTH)])
    country = fields.SelectField(_('Country'), choices=utils.COUNTRIES)

    contribution = fields.TextAreaField(_('Contribution'), [validators.Required(), validators.Length(max=65536)])
    pm = fields.TextAreaField(_('Pm'), [validators.Length(max=160)])
    occupation = fields.TextField(_('Name'), [validators.Required(), validators.Length(max=FIELD_MAXLENGTH)])
    dob = fields.DateField(_('Dob'), [validators.required()]) #future work: regex for date
    avatar = fields.FileField(_('Avatar'))
    p_email = fields.BooleanField(_('Email'))
    p_country = fields.BooleanField(_('Country'))
    p_dob = fields.BooleanField(_('Age'))
    p_fb = fields.BooleanField(_('Facebook'))
    p_twit = fields.BooleanField(_('Twitter'))
    p_link = fields.BooleanField(_('LinkedIn'))
    occ = fields.TextField(_('occ'), [validators.Length(max=FIELD_MAXLENGTH)])
    facebook = fields.TextAreaField(_('Facebook'), [validators.Length(max=160)])
    twitter = fields.TextAreaField(_('Twitter'), [validators.Length(max=160)])
    linkedin = fields.TextAreaField(_('Linkedin'), [validators.Length(max=160)])

class privacyForm(BaseForm):
    p_email = fields.BooleanField(_('p_Email'))
    p_country = fields.BooleanField(_('p_Country'))
    p_dob = fields.BooleanField(_('p_Age'))

class PasswordResetCompleteForm(PasswordMixin, ConfirmPasswordMixin):
    pass


# mobile form does not require c_password as last letter is shown while typing and typing is difficult on mobile
class PasswordResetCompleteMobileForm(PasswordMixin):
    pass


class LoginForm(BaseForm):
    password = fields.TextField(_('Password'), [validators.Required(), validators.Length(max=FIELD_MAXLENGTH)], id='l_password')
    username = fields.TextField(_('Username'), [validators.Required(), validators.Length(max=FIELD_MAXLENGTH)], id='l_username')


class ContactForm(BaseForm):
    email = fields.TextField(_('Email'), [validators.Required(), validators.Length(min=7, max=FIELD_MAXLENGTH), validators.regexp(utils.EMAIL_REGEXP, message=_('Invalid email address.'))])
    name = fields.TextField(_('Name'), [validators.Required(), validators.Length(max=FIELD_MAXLENGTH)])
    message = fields.TextAreaField(_('Message'), [validators.Required(), validators.Length(max=65536)])


class RegisterForm(PasswordMixin, ConfirmPasswordMixin, UserMixin):
    email = fields.TextField(_('Email'), [validators.Required(), validators.Length(min=7, max=FIELD_MAXLENGTH), validators.regexp(utils.EMAIL_REGEXP, message=_('Invalid email address.'))])
    pass


# mobile form does not require c_password as last letter is shown while typing and typing is difficult on mobile
class RegisterMobileForm(PasswordMixin, UserMixin):
    email = fields.TextField(_('Email'), [validators.Required(), validators.Length(min=7, max=FIELD_MAXLENGTH), validators.regexp(utils.EMAIL_REGEXP, message=_('Invalid email address.'))])
    pass


class EditProfileForm(UserMixin):
    pass


class EditPasswordForm(PasswordMixin, ConfirmPasswordMixin, CurrentPasswordMixin):
    pass


# mobile form does not require c_password as last letter is shown while typing and typing is difficult on mobile
class EditPasswordMobileForm(PasswordMixin, CurrentPasswordMixin):
    pass


class EditEmailForm(PasswordMixin):
    new_email = fields.TextField(_('Email'), [validators.Required(), validators.Length(min=7, max=FIELD_MAXLENGTH), validators.regexp(utils.EMAIL_REGEXP, message=_('Invalid email address.'))])
    