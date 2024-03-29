# -*- coding: utf-8 -*-

"""
    A real simple app for using webapp2 with auth and session.

    It just covers the basics. Creating a user, login, logout
    and a decorator for protecting certain handlers.

    Routes are setup in routes.py and added in main.py
"""
# standard library imports
import logging
import random
import re
import json
import time
# related third party imports
import webapp2
import httpagentparser
from webapp2_extras import security
from webapp2_extras.auth import InvalidAuthIdError, InvalidPasswordError
from webapp2_extras.i18n import gettext as _
from webapp2_extras.appengine.auth.models import Unique
from google.appengine.api import taskqueue
from google.appengine.api import users
from google.appengine.api.datastore_errors import BadValueError
from google.appengine.runtime import apiproxy_errors
from github import github
from linkedin import linkedin
from datetime import date
from google.appengine.ext import ndb, db
from PIL import Image
from sets import Set

# local application/library specific imports
import pycountry
import models
import forms as forms
from lib import utils, captcha, twitter
from lib.basehandler import BaseHandler
from lib.basehandler import user_required
from lib import facebook

class AbTestHandler(BaseHandler):
    """
    AB Testing experiments are communly used with landing pages, but is not limited to them.
    If the rendered page contains a form (i.e. newsletter subscription),
    manage the post request in a different handler

    For complex A/B test, you can use the 2 templates instead of one.
    By default only one template is used as abtest_b.html is a soft link to abtest_a.html
    """
    def get(self):
        a = True
        template = 'abtest_a.html'
        if random.randint(0,1) :
            a = False
            template = 'abtest_b.html'
        params = { 'a': a , 'b': not a  }
        return self.render_template(template, **params)

class LoginRequiredHandler(BaseHandler):
    def get(self):
        continue_url, = self.request.get('continue',allow_multiple=True)
        self.redirect(users.create_login_url(dest_url=continue_url))


class RegisterBaseHandler(BaseHandler):
    """
    Base class for handlers with registration and login forms.
    """
    @webapp2.cached_property
    def form(self):
        if self.is_mobile:
            return forms.RegisterMobileForm(self)
        else:
            return forms.RegisterForm(self)


class SendEmailHandler(BaseHandler):
    """
    Core Handler for sending Emails
    Use with TaskQueue
    """
    def post(self):

        from google.appengine.api import mail, app_identity

        to = self.request.get("to")
        subject = self.request.get("subject")
        body = self.request.get("body")
        sender = self.request.get("sender")

        if sender != '' or not utils.is_email_valid(sender):
            if utils.is_email_valid(self.app.config.get('contact_sender')):
                sender = self.app.config.get('contact_sender')
            else:
                app_id = app_identity.get_application_id()
                sender = "%s <no-reply@%s.appspotmail.com>" % (app_id, app_id)

        if self.app.config['log_email']:
            try:
                logEmail = models.LogEmail(
                    sender = sender,
                    to = to,
                    subject = subject,
                    body = body,
                    when = utils.get_date_time("datetimeProperty")
                )
                logEmail.put()
            except (apiproxy_errors.OverQuotaError, BadValueError):
                logging.error("Error saving Email Log in datastore")

        message = mail.EmailMessage()
        message.sender=sender
        message.to=to
        message.subject=subject
        message.html=body
        message.send()


class LoginHandler(BaseHandler):
    """
    Handler for authentication
    """

    def get(self):
        """ Returns a simple HTML form for login """

        if self.user:
            self.redirect_to('home')
        params = {}
        return self.render_template('login.html', **params)

    def post(self):
        """
        username: Get the username from POST dict
        password: Get the password from POST dict
        """

        if not self.form.validate():
            return self.get()
        username = self.form.username.data.lower()
        continue_url = self.request.get('continue_url').encode('ascii', 'ignore')

        try:
            if utils.is_email_valid(username):
                user = models.User.get_by_email(username)
                if user:
                    auth_id = user.auth_ids[0]
                else:
                    raise InvalidAuthIdError
            else:
                auth_id = "own:%s" % username
                user = models.User.get_by_auth_id(auth_id)

            password = self.form.password.data.strip()
            remember_me = True if str(self.request.POST.get('remember_me')) == 'on' else False

            # Password to SHA512
            password = utils.hashing(password, self.app.config.get('salt'))

            # Try to login user with password
            # Raises InvalidAuthIdError if user is not found
            # Raises InvalidPasswordError if provided password
            # doesn't match with specified user
            self.auth.get_user_by_password(
                auth_id, password, remember=remember_me)

            # if user account is not activated, logout and redirect to home
            if (user.activated == False):
                # logout
                self.auth.unset_session()

                # redirect to home with error message
                resend_email_uri = self.uri_for('resend-account-activation', user_id=user.get_id(),
                                                token=models.User.create_resend_token(user.get_id()))
                message = _('Your account has not yet been activated. Please check your email to activate it or') +\
                          ' <a href="'+resend_email_uri+'">' + _('click here') + '</a> ' + _('to resend the email.')
                self.add_message(message, 'error')
                return self.redirect_to('home')

            # check twitter association in session
            twitter_helper = twitter.TwitterAuth(self)
            twitter_association_data = twitter_helper.get_association_data()
            if twitter_association_data is not None:
                if models.SocialUser.check_unique(user.key, 'twitter', str(twitter_association_data['id'])):
                    social_user = models.SocialUser(
                        user = user.key,
                        provider = 'twitter',
                        uid = str(twitter_association_data['id']),
                        extra_data = twitter_association_data
                    )
                    social_user.put()

            # check facebook association
            fb_data = None
            try:
                fb_data = json.loads(self.session['facebook'])
            except:
                pass

            if fb_data is not None:
                if models.SocialUser.check_unique(user.key, 'facebook', str(fb_data['id'])):
                    social_user = models.SocialUser(
                        user = user.key,
                        provider = 'facebook',
                        uid = str(fb_data['id']),
                        extra_data = fb_data
                    )
                    social_user.put()

            # check linkedin association
            li_data = None
            try:
                li_data = json.loads(self.session['linkedin'])
            except:
                pass
            if li_data is not None:
                if models.SocialUser.check_unique(user.key, 'linkedin', str(li_data['id'])):
                    social_user = models.SocialUser(
                        user = user.key,
                        provider = 'linkedin',
                        uid = str(li_data['id']),
                        extra_data = li_data
                    )
                    social_user.put()

            # end linkedin

            if self.app.config['log_visit']:
                try:
                    logVisit = models.LogVisit(
                        user=user.key,
                        uastring=self.request.user_agent,
                        ip=self.request.remote_addr,
                        timestamp=utils.get_date_time()
                    )
                    logVisit.put()
                except (apiproxy_errors.OverQuotaError, BadValueError):
                    logging.error("Error saving Visit Log in datastore")
            if continue_url:
                self.redirect(continue_url)
            else:
                self.redirect_to('home')
        except (InvalidAuthIdError, InvalidPasswordError), e:
            # Returns error message to self.response.write in
            # the BaseHandler.dispatcher
            message = _("Your username or password is incorrect. "
                        "Please try again (make sure your caps lock is off)")
            self.add_message(message, 'error')
            self.redirect_to('home', continue_url=continue_url) if continue_url else self.redirect_to('home')

    @webapp2.cached_property
    def form(self):
        return forms.LoginForm(self)


class SocialLoginHandler(BaseHandler):
    """
    Handler for Social authentication
    """

    def get(self, provider_name):
        provider = self.provider_info[provider_name]

        if not self.app.config.get('enable_federated_login'):
            message = _('Federated login is disabled.')
            self.add_message(message, 'warning')
            return self.redirect_to('login')
        callback_url = "%s/social_login/%s/complete" % (self.request.host_url, provider_name)

        if provider_name == "twitter":
            twitter_helper = twitter.TwitterAuth(self, redirect_uri=callback_url)
            self.redirect(twitter_helper.auth_url())

        elif provider_name == "facebook":
            self.session['linkedin'] = None
            perms = ['email', 'publish_stream']
            self.redirect(facebook.auth_url(self.app.config.get('fb_api_key'), callback_url, perms))

        elif provider_name == 'linkedin':
            self.session['facebook'] = None
            authentication = linkedin.LinkedInAuthentication(
                self.app.config.get('linkedin_api'),
                self.app.config.get('linkedin_secret'),
                callback_url,
                [linkedin.PERMISSIONS.BASIC_PROFILE, linkedin.PERMISSIONS.EMAIL_ADDRESS])
            self.redirect(authentication.authorization_url)

        elif provider_name == "github":
            scope = 'gist'
            github_helper = github.GithubAuth(self.app.config.get('github_server'), self.app.config.get('github_client_id'), \
                                              self.app.config.get('github_client_secret'), self.app.config.get('github_redirect_uri'), scope)
            self.redirect( github_helper.get_authorize_url() )

        elif provider_name in models.SocialUser.open_id_providers():
            continue_url = self.request.get('continue_url')
            if continue_url:
                dest_url=self.uri_for('social-login-complete', provider_name=provider_name, continue_url=continue_url)
            else:
                dest_url=self.uri_for('social-login-complete', provider_name=provider_name)
            try:
                login_url = users.create_login_url(federated_identity=provider['uri'], dest_url=dest_url)
                self.redirect(login_url)
            except users.NotAllowedError:
                self.add_message('You must enable Federated Login Before for this application.<br> '
                                '<a href="http://appengine.google.com" target="_blank">Google App Engine Control Panel</a> -> '
                                'Administration -> Application Settings -> Authentication Options', 'error')
                self.redirect_to('login')

        else:
            message = _('%s authentication is not yet implemented.' % provider.get('label'))
            self.add_message(message, 'warning')
            self.redirect_to('login')


class CallbackSocialLoginHandler(BaseHandler):
    """
    Callback (Save Information) for Social Authentication
    """

    def get(self, provider_name):
        if not self.app.config.get('enable_federated_login'):
            message = _('Federated login is disabled.')
            self.add_message(message, 'warning')
            return self.redirect_to('login')
        continue_url = self.request.get('continue_url')
        if provider_name == "twitter":
            oauth_token = self.request.get('oauth_token')
            oauth_verifier = self.request.get('oauth_verifier')
            twitter_helper = twitter.TwitterAuth(self)
            user_data = twitter_helper.auth_complete(oauth_token,
                oauth_verifier)
            logging.info('twitter user_data: ' + str(user_data))
            if self.user:
                # new association with twitter
                user_info = models.User.get_by_id(long(self.user_id))
                if models.SocialUser.check_unique(user_info.key, 'twitter', str(user_data['user_id'])):
                    social_user = models.SocialUser(
                        user = user_info.key,
                        provider = 'twitter',
                        uid = str(user_data['user_id']),
                        extra_data = user_data
                    )
                    social_user.put()

                    message = _('Twitter association added.')
                    self.add_message(message, 'success')
                else:
                    message = _('This Twitter account is already in use.')
                    self.add_message(message, 'error')
                if continue_url:
                    self.redirect(continue_url)
                else:
                    self.redirect_to('edit-profile')
            else:
                # login with twitter
                social_user = models.SocialUser.get_by_provider_and_uid('twitter',
                    str(user_data['user_id']))
                if social_user:
                    # Social user exists. Need authenticate related site account
                    user = social_user.user.get()
                    self.auth.set_session(self.auth.store.user_to_dict(user), remember=True)
                    if self.app.config['log_visit']:
                        try:
                            logVisit = models.LogVisit(
                                user=user.key,
                                uastring=self.request.user_agent,
                                ip=self.request.remote_addr,
                                timestamp=utils.get_date_time()
                            )
                            logVisit.put()
                        except (apiproxy_errors.OverQuotaError, BadValueError):
                            logging.error("Error saving Visit Log in datastore")
                    if continue_url:
                        self.redirect(continue_url)
                    else:
                        self.redirect_to('home')
                else:
                    uid = str(user_data['user_id'])
                    email = str(user_data.get('email'))
                    self.create_account_from_social_provider(provider_name, uid, email, continue_url, user_data)

        # github association
        elif provider_name == "github":
            # get our request code back from the social login handler above
            code = self.request.get('code')

            # create our github auth object
            scope = 'gist'
            github_helper = github.GithubAuth(self.app.config.get('github_server'), self.app.config.get('github_client_id'), \
                                              self.app.config.get('github_client_secret'), self.app.config.get('github_redirect_uri'), scope)

            # retrieve the access token using the code and auth object
            access_token = github_helper.get_access_token(code)
            user_data = github_helper.get_user_info(access_token)
            logging.info('github user_data: ' + str(user_data))
            if self.user:
                # user is already logged in so we set a new association with twitter
                user_info = models.User.get_by_id(long(self.user_id))
                if models.SocialUser.check_unique(user_info.key, 'github', str(user_data['login'])):
                    social_user = models.SocialUser(
                        user = user_info.key,
                        provider = 'github',
                        uid = str(user_data['login']),
                        extra_data = user_data
                    )
                    social_user.put()

                    message = _('Github association added.')
                    self.add_message(message, 'success')
                else:
                    message = _('This Github account is already in use.')
                    self.add_message(message, 'error')
                self.redirect_to('edit-profile')
            else:
                # user is not logged in, but is trying to log in via github
                social_user = models.SocialUser.get_by_provider_and_uid('github', str(user_data['login']))
                if social_user:
                    # Social user exists. Need authenticate related site account
                    user = social_user.user.get()
                    self.auth.set_session(self.auth.store.user_to_dict(user), remember=True)
                    if self.app.config['log_visit']:
                        try:
                            logVisit = models.LogVisit(
                                user=user.key,
                                uastring=self.request.user_agent,
                                ip=self.request.remote_addr,
                                timestamp=utils.get_date_time()
                            )
                            logVisit.put()
                        except (apiproxy_errors.OverQuotaError, BadValueError):
                            logging.error("Error saving Visit Log in datastore")
                    self.redirect_to('home')
                else:
                    uid = str(user_data['id'])
                    email = str(user_data.get('email'))
                    self.create_account_from_social_provider(provider_name, uid, email, continue_url, user_data)
        #end github

        # facebook association
        elif provider_name == "facebook":
            code = self.request.get('code')
            callback_url = "%s/social_login/%s/complete" % (self.request.host_url, provider_name)
            token = facebook.get_access_token_from_code(code, callback_url, self.app.config.get('fb_api_key'), self.app.config.get('fb_secret'))
            access_token = token['access_token']
            fb = facebook.GraphAPI(access_token)
            user_data = fb.get_object('me')
            logging.info('facebook user_data: ' + str(user_data))
            if self.user:
                # new association with facebook
                user_info = models.User.get_by_id(long(self.user_id))
                if models.SocialUser.check_unique(user_info.key, 'facebook', str(user_data['id'])):
                    social_user = models.SocialUser(
                        user = user_info.key,
                        provider = 'facebook',
                        uid = str(user_data['id']),
                        extra_data = user_data
                    )
                    social_user.put()

                    message = _('Facebook association added!')
                    self.add_message(message,'success')
                else:
                    message = _('This Facebook account is already in use!')
                    self.add_message(message,'error')
                if continue_url:
                    self.redirect(continue_url)
                else:
                    self.redirect_to('edit-profile')
            else:
                # login with Facebook
                social_user = models.SocialUser.get_by_provider_and_uid('facebook',
                    str(user_data['id']))
                if social_user:
                    # Social user exists. Need authenticate related site account
                    user = social_user.user.get()
                    self.auth.set_session(self.auth.store.user_to_dict(user), remember=True)
                    if self.app.config['log_visit']:
                        try:
                            logVisit = models.LogVisit(
                                user=user.key,
                                uastring=self.request.user_agent,
                                ip=self.request.remote_addr,
                                timestamp=utils.get_date_time()
                            )
                            logVisit.put()
                        except (apiproxy_errors.OverQuotaError, BadValueError):
                            logging.error("Error saving Visit Log in datastore")
                    if continue_url:
                        self.redirect(continue_url)
                    else:
                        self.redirect_to('home')
                else:
                    uid = str(user_data['id'])
                    email = str(user_data.get('email'))
                    self.create_account_from_social_provider(provider_name, uid, email, continue_url, user_data)

            # end facebook
        # association with linkedin
        elif provider_name == "linkedin":
            callback_url = "%s/social_login/%s/complete" % (self.request.host_url, provider_name)
            authentication = linkedin.LinkedInAuthentication(
                self.app.config.get('linkedin_api'),
                self.app.config.get('linkedin_secret'),
                callback_url,
                [linkedin.PERMISSIONS.BASIC_PROFILE, linkedin.PERMISSIONS.EMAIL_ADDRESS])
            authentication.authorization_code = self.request.get('code')
            access_token = authentication.get_access_token()
            link = linkedin.LinkedInApplication(authentication)
            u_data = link.get_profile(selectors=['id','first-name','last-name', 'email-address'])
            user_data={
                'first_name':u_data.get('firstName'),
                'last_name':u_data.get('lastName'),
                'id':u_data.get('id'),
                'email':u_data.get('emailAddress')}
            self.session['linkedin'] = json.dumps(user_data)
            logging.info('linkedin user_data: ' + str(user_data))

            if self.user:
                # new association with linkedin
                user_info = models.User.get_by_id(long(self.user_id))
                if models.SocialUser.check_unique(user_info.key, 'linkedin', str(user_data['id'])):
                    social_user = models.SocialUser(
                        user = user_info.key,
                        provider = 'linkedin',
                        uid = str(user_data['id']),
                        extra_data = user_data
                    )
                    social_user.put()

                    message = _('Linkedin association added!')
                    self.add_message(message,'success')
                else:
                    message = _('This Linkedin account is already in use!')
                    self.add_message(message,'error')
                if continue_url:
                    self.redirect(continue_url)
                else:
                    self.redirect_to('edit-profile')
            else:
                # login with Linkedin
                social_user = models.SocialUser.get_by_provider_and_uid('linkedin',
                    str(user_data['id']))
                if social_user:
                    # Social user exists. Need authenticate related site account
                    user = social_user.user.get()
                    self.auth.set_session(self.auth.store.user_to_dict(user), remember=True)
                    if self.app.config['log_visit']:
                        try:
                            logVisit = models.LogVisit(
                                user=user.key,
                                uastring=self.request.user_agent,
                                ip=self.request.remote_addr,
                                timestamp=utils.get_date_time()
                            )
                            logVisit.put()
                        except (apiproxy_errors.OverQuotaError, BadValueError):
                            logging.error("Error saving Visit Log in datastore")
                    if continue_url:
                        self.redirect(continue_url)
                    else:
                        self.redirect_to('home')
                else:
                    uid = str(user_data['id'])
                    email = str(user_data.get('email'))
                    self.create_account_from_social_provider(provider_name, uid, email, continue_url, user_data)

            #end linkedin

        # google, myopenid, yahoo OpenID Providers
        elif provider_name in models.SocialUser.open_id_providers():
            provider_display_name = models.SocialUser.PROVIDERS_INFO[provider_name]['label']
            # get info passed from OpenId Provider
            from google.appengine.api import users
            current_user = users.get_current_user()
            if current_user:
                if current_user.federated_identity():
                    uid = current_user.federated_identity()
                else:
                    uid = current_user.user_id()
                email = current_user.email()
            else:
                message = _('No user authentication information received from %s. '
                            'Please ensure you are logging in from an authorized OpenID Provider (OP).'
                            % provider_display_name)
                self.add_message(message, 'error')
                return self.redirect_to('login', continue_url=continue_url) if continue_url else self.redirect_to('login')
            if self.user:
                # add social account to user
                user_info = models.User.get_by_id(long(self.user_id))
                if models.SocialUser.check_unique(user_info.key, provider_name, uid):
                    social_user = models.SocialUser(
                        user = user_info.key,
                        provider = provider_name,
                        uid = uid
                    )
                    social_user.put()

                    message = _('%s association successfully added.' % provider_display_name)
                    self.add_message(message, 'success')
                else:
                    message = _('This %s account is already in use.' % provider_display_name)
                    self.add_message(message, 'error')
                if continue_url:
                    self.redirect(continue_url)
                else:
                    self.redirect_to('edit-profile')
            else:
                # login with OpenId Provider
                social_user = models.SocialUser.get_by_provider_and_uid(provider_name, uid)
                if social_user:
                    # Social user found. Authenticate the user
                    user = social_user.user.get()
                    self.auth.set_session(self.auth.store.user_to_dict(user), remember=True)
                    if self.app.config['log_visit']:
                        try:
                            logVisit = models.LogVisit(
                                user=user.key,
                                uastring=self.request.user_agent,
                                ip=self.request.remote_addr,
                                timestamp=utils.get_date_time()
                            )
                            logVisit.put()
                        except (apiproxy_errors.OverQuotaError, BadValueError):
                            logging.error("Error saving Visit Log in datastore")
                    if continue_url:
                        self.redirect(continue_url)
                    else:
                        self.redirect_to('home')
                else:
                    self.create_account_from_social_provider(provider_name, uid, email, continue_url)
        else:
            message = _('This authentication method is not yet implemented.')
            self.add_message(message, 'warning')
            self.redirect_to('login', continue_url=continue_url) if continue_url else self.redirect_to('login')

    def create_account_from_social_provider(self, provider_name, uid, email=None, continue_url=None, user_data=None):
        """Social user does not exist yet so create it with the federated identity provided (uid)
        and create prerequisite user and log the user account in
        """
        provider_display_name = models.SocialUser.PROVIDERS_INFO[provider_name]['label']
        if models.SocialUser.check_unique_uid(provider_name, uid):
            # create user
            # Returns a tuple, where first value is BOOL.
            # If True ok, If False no new user is created
            # Assume provider has already verified email address
            # if email is provided so set activated to True
            auth_id = "%s:%s" % (provider_name, uid)
            if email:
                unique_properties = ['email']
                user_info = self.auth.store.user_model.create_user(
                    auth_id, unique_properties, email=email,
                    activated=True
                )
            else:
                user_info = self.auth.store.user_model.create_user(
                    auth_id, activated=True
                )
            if not user_info[0]: #user is a tuple
                message = _('The account %s is already in use.' % provider_display_name)
                self.add_message(message, 'error')
                return self.redirect_to('register')

            user = user_info[1]

            # create social user and associate with user
            social_user = models.SocialUser(
                user = user.key,
                provider = provider_name,
                uid = uid,
            )
            if user_data:
                social_user.extra_data = user_data
                self.session[provider_name] = json.dumps(user_data) # TODO is this needed?
            social_user.put()
            # authenticate user
            self.auth.set_session(self.auth.store.user_to_dict(user), remember=True)
            if self.app.config['log_visit']:
                try:
                    logVisit = models.LogVisit(
                        user=user.key,
                        uastring=self.request.user_agent,
                        ip=self.request.remote_addr,
                        timestamp=utils.get_date_time()
                    )
                    logVisit.put()
                except (apiproxy_errors.OverQuotaError, BadValueError):
                    logging.error("Error saving Visit Log in datastore")

            message = _('Welcome!  You have been registered as a new user through %s and logged in.' % provider_display_name)
            self.add_message(message, 'success')
        else:
            message = _('This %s account is already in use.' % provider_display_name)
            self.add_message(message, 'error')
        if continue_url:
            self.redirect(continue_url)
        else:
            self.redirect_to('edit-profile')

class DeleteSocialProviderHandler(BaseHandler):
    """
    Delete Social association with an account
    """

    @user_required
    def post(self, provider_name):
        if self.user:
            user_info = models.User.get_by_id(long(self.user_id))
            if len(user_info.get_social_providers_info()['used']) > 1 or (user_info.password is not None):
                social_user = models.SocialUser.get_by_user_and_provider(user_info.key, provider_name)
                if social_user:
                    social_user.key.delete()
                    message = _('%s successfully disassociated.' % provider_name)
                    self.add_message(message, 'success')
                else:
                    message = _('Social account on %s not found for this user.' % provider_name)
                    self.add_message(message, 'error')
            else:
                message = ('Social account on %s cannot be deleted for user.'
                            '  Please create a username and password to delete social account.' % provider_name)
                self.add_message(message, 'error')
        self.redirect_to('edit-profile')


class LogoutHandler(BaseHandler):
    """
    Destroy user session and redirect to login
    """

    def get(self):
        if self.user:
            message = _("You've signed out successfully. Warning: Please clear all cookies and logout "
                        "of OpenId providers too if you logged in on a public computer.")
            self.add_message(message, 'info')

        self.auth.unset_session()
        return self.redirect_to('home')
        # User is logged out, let's try redirecting to login page
        try:
            self.redirect(self.auth_config['login_url'])
        except (AttributeError, KeyError), e:
            logging.error("Error logging out: %s" % e)
            message = _("User is logged out, but there was an error on the redirection.")
            self.add_message(message, 'error')
            return self.redirect_to('home')


class RegisterHandler(RegisterBaseHandler):
    """
    Handler for Sign Up Users
    """
    @classmethod
    def is_png(self, file):
        try:
            i=Image.open(file)
            return i.format =='JPEG'
        except IOError:
            return False

    def get(self):
        """ Returns a simple HTML form for create a new user """

        if self.user:
            self.redirect_to('home')
        params = {}
        return self.render_template('register.html', **params)

    def post(self):
        """ Get fields from POST dict """

        if not self.form.validate():
            return self.get()
        username = self.form.username.data.lower()
        name = self.form.name.data.strip()
        last_name = self.form.last_name.data.strip()
        email = self.form.email.data.lower()
        password = self.form.password.data.strip()
        country = self.form.country.data
        occupation = self.form.occupation.data
        contribution = self.form.contribution.data
        pm = self.form.pm.data
        dob = self.form.dob.data
        id_no = models.User.id_gen() + 1
        # Password to SHA512
        password = utils.hashing(password, self.app.config.get('salt'))
        avatar = self.request.get('avatar')
        facebook = self.form.facebook.data.strip()
        twitter1 = self.form.twitter.data.strip()
        linkedin1 = self.form.linkedin.data.strip()



        # Passing password_raw=password so password will be hashed
        # Returns a tuple, where first value is BOOL.
        # If True ok, If False no new user is created
        unique_properties = ['username', 'email']
        auth_id = "own:%s" % username
        user = self.auth.store.user_model.create_user(
            auth_id, unique_properties, password_raw=password,
            username=username, name=name, last_name=last_name, email=email,
            ip=self.request.remote_addr, country=country, occupation=occupation,
            contribution=contribution, pm=pm, dob=dob, id_no=id_no, facebook=facebook, twitter=twitter1, linkedin=linkedin1
        )

        priv = models.Privacy(id_no=id_no)
        priv.put()

        if not user[0]: #user is a tuple
            if "username" in str(user[1]):
                message = _('Sorry, The username %s is already registered.' % '<strong>{0:>s}</strong>'.format(username) )
            elif "email" in str(user[1]):
                message = _('Sorry, The email %s is already registered.' % '<strong>{0:>s}</strong>'.format(email) )
            else:
                message = _('Sorry, The user is already registered.')
            self.add_message(message, 'error')
            return self.redirect_to('home')
        else:
            # User registered successfully
            # But if the user registered using the form, the user has to check their email to activate the account ???
            try:

                time.sleep(0.5)
                user_info = models.User.get_by_email(email)
                try:
                    user_info.avatar = db.Blob(avatar)
                    user_info.put()
                except:
                    pass

                try:
                    user_obj = models.Privacy.get_by_id(id_no)
                    user_obj.country = True
                    user_obj.email = True
                    user_obj.dob = True
                    user_obj.fb = True
                    user_obj.twit = True
                    user_obj.link = True
                    user_obj.put()
                except:
                    pass

                if (user_info.activated == False):
                    # send email
                    subject =  _("%s Account Verification" % self.app.config.get('app_name'))
                    confirmation_url = self.uri_for("account-activation",
                        user_id=user_info.get_id(),
                        token = models.User.create_auth_token(user_info.get_id()),
                        _full = True)

                    # load email's template
                    template_val = {
                        "app_name": self.app.config.get('app_name'),
                        "username": username,
                        "confirmation_url": confirmation_url,
                        "support_url": self.uri_for("contact", _full=True)
                    }
                    body_path = "emails/account_activation.txt"
                    body = self.jinja2.render_template(body_path, **template_val)

                    email_url = self.uri_for('taskqueue-send-email')
                    taskqueue.add(url = email_url, params={
                        'to': str(email),
                        'subject' : subject,
                        'body' : body,
                        })

                    message = _('You were successfully registered. '
                                'Please check your email to activate your account. ' )
                    self.add_message(message, 'success')
                    return self.redirect_to('home')

                # If the user didn't register using registration form ???
                db_user = self.auth.get_user_by_password(user[1].auth_ids[0], password)
                # Check twitter association in session
                twitter_helper = twitter.TwitterAuth(self)
                twitter_association_data = twitter_helper.get_association_data()
                if twitter_association_data is not None:
                    if models.SocialUser.check_unique(user[1].key, 'twitter', str(twitter_association_data['id'])):
                        social_user = models.SocialUser(
                            user = user[1].key,
                            provider = 'twitter',
                            uid = str(twitter_association_data['id']),
                            extra_data = twitter_association_data
                        )
                        social_user.put()

                #check facebook association
                fb_data = json.loads(self.session['facebook'])

                if fb_data is not None:
                    if models.SocialUser.check_unique(user.key, 'facebook', str(fb_data['id'])):
                        social_user = models.SocialUser(
                            user = user.key,
                            provider = 'facebook',
                            uid = str(fb_data['id']),
                            extra_data = fb_data
                        )
                        social_user.put()
                #check linkedin association
                li_data = json.loads(self.session['linkedin'])
                if li_data is not None:
                    if models.SocialUser.check_unique(user.key, 'linkedin', str(li_data['id'])):
                        social_user = models.SocialUser(
                            user = user.key,
                            provider = 'linkedin',
                            uid = str(li_data['id']),
                            extra_data = li_data
                        )
                        social_user.put()


                message = _('Welcome %s, you are now logged in.' % '<strong>{0:>s}</strong>'.format(username) )
                self.add_message(message, 'success')
                return self.redirect_to('home')
            except (AttributeError, KeyError), e:
                logging.error('Unexpected error creating the user %s: %s' % (username, e ))
                message = _('Unexpected error creating the user %s' % username )
                #message = _('Unexpected error creating the user %s' % username )
                self.add_message(message, 'error')
                return self.redirect_to('home')


class AccountActivationHandler(BaseHandler):
    """
    Handler for account activation
    """

    def get(self, user_id, token):
        try:
            if not models.User.validate_auth_token(user_id, token):
                message = _('The link is invalid.')
                self.add_message(message, 'error')
                return self.redirect_to('home')

            user = models.User.get_by_id(long(user_id))
            # activate the user's account
            user.activated = True
            user.put()

            # Login User
            self.auth.get_user_by_token(int(user_id), token)

            # Delete token
            models.User.delete_auth_token(user_id, token)

            message = _('Congratulations, Your account %s has been successfully activated.'
                        % '<strong>{0:>s}</strong>'.format(user.username) )
            self.add_message(message, 'success')
            self.redirect_to('home')

        except (AttributeError, KeyError, InvalidAuthIdError, NameError), e:
            logging.error("Error activating an account: %s" % e)
            message = _('Sorry, Some error occurred.')
            self.add_message(message, 'error')
            return self.redirect_to('home')


class ResendActivationEmailHandler(BaseHandler):
    """
    Handler to resend activation email
    """

    def get(self, user_id, token):
        try:
            if not models.User.validate_resend_token(user_id, token):
                message = _('The link is invalid.')
                self.add_message(message, 'error')
                return self.redirect_to('home')

            user = models.User.get_by_id(long(user_id))
            email = user.email

            if (user.activated == False):
                # send email
                subject = _("%s Account Verification" % self.app.config.get('app_name'))
                confirmation_url = self.uri_for("account-activation",
                    user_id = user.get_id(),
                    token = models.User.create_auth_token(user.get_id()),
                    _full = True)

                # load email's template
                template_val = {
                    "app_name": self.app.config.get('app_name'),
                    "username": user.username,
                    "confirmation_url": confirmation_url,
                    "support_url": self.uri_for("contact", _full=True)
                }
                body_path = "emails/account_activation.txt"
                body = self.jinja2.render_template(body_path, **template_val)

                email_url = self.uri_for('taskqueue-send-email')
                taskqueue.add(url = email_url, params={
                    'to': str(email),
                    'subject' : subject,
                    'body' : body,
                    })

                models.User.delete_resend_token(user_id, token)

                message = _('The verification email has been resent to %s. '
                            'Please check your email to activate your account.' % email)
                self.add_message(message, 'success')
                return self.redirect_to('home')
            else:
                message = _('Your account has been activated. Please <a href="/login/">sign in</a> to your account.')
                self.add_message(message, 'warning')
                return self.redirect_to('home')

        except (KeyError, AttributeError), e:
            logging.error("Error resending activation email: %s" % e)
            message = _('Sorry, Some error occurred.')
            self.add_message(message, 'error')
            return self.redirect_to('home')


class ContactHandler(BaseHandler):
    """
    Handler for Contact Form
    """

    def get(self):
        """ Returns a simple HTML for contact form """

        if self.user:
            user_info = models.User.get_by_id(long(self.user_id))
            if user_info.name or user_info.last_name:
                self.form.name.data = user_info.name + " " + user_info.last_name
            if user_info.email:
                self.form.email.data = user_info.email
        params = {
            "exception" : self.request.get('exception')
            }

        return self.render_template('contact.html', **params)

    def post(self):
        """ validate contact form """

        if not self.form.validate():
            return self.get()
        remoteip  = self.request.remote_addr
        user_agent  = self.request.user_agent
        exception = self.request.POST.get('exception')
        name = self.form.name.data.strip()
        email = self.form.email.data.lower()
        message = self.form.message.data.strip()

        try:
            # parsing user_agent and getting which os key to use
            # windows uses 'os' while other os use 'flavor'
            logging.info(user_agent)
            ua = httpagentparser.detect(user_agent)
            os = ua.has_key('flavor') and 'flavor' or 'os'

            operating_system_full_name = str(ua[os]['name'])

            if 'version' in ua[os]:
                operating_system_full_name += ' '+str(ua[os]['version'])

            if 'dist' in ua:
                operating_system_full_name += ' '+str(ua['dist'])

            template_val = {
                "name": name,
                "email": email,
                "browser": str(ua['browser']['name']),
                "browser_version": str(ua['browser']['version']),
                "operating_system": operating_system_full_name,
                "ip": remoteip,
                "message": message
            }
        except Exception as e:
            logging.error("error getting user agent info: %s" % e)

        try:
            subject = _("Contact")
            # exceptions for error pages that redirect to contact
            if exception != "":
                subject = subject + " (Exception error: %s)" % exception

            body_path = "emails/contact.txt"
            body = self.jinja2.render_template(body_path, **template_val)

            email_url = self.uri_for('taskqueue-send-email')
            taskqueue.add(url = email_url, params={
                'to': self.app.config.get('contact_recipient'),
                'subject' : subject,
                'body' : body,
                'sender' : self.app.config.get('contact_sender'),
                })

            message = _('Your message was sent successfully.')
            self.add_message(message, 'success')
            return self.redirect_to('thankyou')

        except (AttributeError, KeyError), e:
            logging.error('Error sending contact form: %s' % e)
            message = _('Error sending the message. Please try again later.')
            self.add_message(message, 'error')
            return self.redirect_to('home')

    @webapp2.cached_property
    def form(self):
        return forms.ContactForm(self)


class EditProfileHandler(BaseHandler):
    """
    Handler for Edit User Profile
    """
    @classmethod
    def is_png(self, file):
        try:
            i=Image.open(file)
            return i.format =='JPEG'
        except IOError:
            return False

    @user_required
    def get(self):
        """ Returns a simple HTML form for edit profile """
        params = {}
        if self.user:
            user_info = models.User.get_by_id(long(self.user_id))
            self.form.username.data = user_info.username
            self.form.name.data = user_info.name
            self.form.last_name.data = user_info.last_name
            self.form.country.data = user_info.country
            self.form.pm.data = user_info.pm
            self.form.contribution.data = user_info.contribution
            self.form.occupation.data = user_info.occupation
            self.form.dob.data = user_info.dob
            self.form.facebook.data = user_info.facebook
            self.form.twitter.data = user_info.twitter
            self.form.linkedin.data = user_info.linkedin

            providers_info = user_info.get_social_providers_info()
            if not user_info.password:
                params['local_account'] = False
            else:
                params['local_account'] = True
            params['used_providers'] = providers_info['used']
            params['unused_providers'] = providers_info['unused']
            params['country'] = user_info.country

        return self.render_template('edit_profile.html', **params)

    def post(self):
        """ Get fields from POST dict """

        if not self.form.validate():
            return self.get()
        username = self.form.username.data.lower()
        name = self.form.name.data.strip()
        last_name = self.form.last_name.data.strip()
        country = self.form.country.data
        pm = self.form.pm.data
        contribution = self.form.contribution.data
        occupation = self.form.occupation.data
        dob = self.form.dob.data
        avatar = self.request.get('avatar')
        facebook = self.form.facebook.data.strip()
        twitter = self.form.twitter.data.strip()
        linkedin = self.form.linkedin.data.strip()

        try:
            user_info = models.User.get_by_id(long(self.user_id))
            try:
                message=''
                # update username if it has changed and it isn't already taken
                if username != user_info.username:
                    user_info.unique_properties = ['username','email']
                    uniques = [
                               'User.username:%s' % username,
                               'User.auth_id:own:%s' % username,
                               ]
                    # Create the unique username and auth_id.
                    success, existing = Unique.create_multi(uniques)
                    if success:
                        # free old uniques
                        Unique.delete_multi(['User.username:%s' % user_info.username, 'User.auth_id:own:%s' % user_info.username])
                        # The unique values were created, so we can save the user.
                        user_info.username=username
                        user_info.auth_ids[0]='own:%s' % username
                        message+= _('Your new username is %s' % '<strong>{0:>s}</strong>'.format(username) )

                    else:
                        message+= _('The username %s is already taken. Please choose another.'
                                % '<strong>{0:>s}</strong>'.format(username) )
                        # At least one of the values is not unique.
                        self.add_message(message, 'error')
                        return self.get()
                user_info.name=name
                user_info.last_name=last_name
                user_info.country=country
                user_info.pm = pm
                user_info.contribution = contribution
                user_info.occupation = occupation
                user_info.dob = dob
                user_info.facebook = facebook
                user_info.twitter = twitter
                user_info.linkedin = linkedin
                user_info.put()


                try:
                    user_info = db.Blob(avatar)
                    user_info.put()
                except:
                    pass

                message+= " " + _('Thanks, your settings have been saved.')
                self.add_message(message, 'success')
                return self.get()

            except (AttributeError, KeyError, ValueError), e:
                logging.error('Error updating profile: ' + e)
                message = _('Unable to update profile. Please try again later.')
                self.add_message(message, 'error')
                return self.get()

        except (AttributeError, TypeError), e:
            logging.error('Error updating profile: ' + str(e))
            login_error_message = _('Sorry you are not logged in.')
            self.add_message(login_error_message, 'error')
            self.redirect_to('login')

    @webapp2.cached_property
    def form(self):
        return forms.EditProfileForm(self)


class EditPasswordHandler(BaseHandler):
    """
    Handler for Edit User Password
    """

    @user_required
    def get(self):
        """ Returns a simple HTML form for editing password """

        params = {}
        return self.render_template('edit_password.html', **params)

    def post(self):
        """ Get fields from POST dict """

        if not self.form.validate():
            return self.get()
        current_password = self.form.current_password.data.strip()
        password = self.form.password.data.strip()

        try:
            user_info = models.User.get_by_id(long(self.user_id))
            auth_id = "own:%s" % user_info.username

            # Password to SHA512
            current_password = utils.hashing(current_password, self.app.config.get('salt'))
            try:
                user = models.User.get_by_auth_password(auth_id, current_password)
                # Password to SHA512
                password = utils.hashing(password, self.app.config.get('salt'))
                user.password = security.generate_password_hash(password, length=12)
                user.put()

                # send email
                subject = self.app.config.get('app_name') + " Account Password Changed"

                # load email's template
                template_val = {
                    "app_name": self.app.config.get('app_name'),
                    "first_name": user.name,
                    "username": user.username,
                    "email": user.email,
                    "reset_password_url": self.uri_for("password-reset", _full=True)
                }
                email_body_path = "emails/password_changed.txt"
                email_body = self.jinja2.render_template(email_body_path, **template_val)
                email_url = self.uri_for('taskqueue-send-email')
                taskqueue.add(url = email_url, params={
                    'to': user.email,
                    'subject' : subject,
                    'body' : email_body,
                    'sender' : self.app.config.get('contact_sender'),
                    })

                #Login User
                self.auth.get_user_by_password(user.auth_ids[0], password)
                self.add_message(_('Password changed successfully.'), 'success')
                return self.redirect_to('edit-profile')
            except (InvalidAuthIdError, InvalidPasswordError), e:
                # Returns error message to self.response.write in
                # the BaseHandler.dispatcher
                message = _("Incorrect password! Please enter your current password to change your account settings.")
                self.add_message(message, 'error')
                return self.redirect_to('edit-password')
        except (AttributeError,TypeError), e:
            login_error_message = _('Sorry you are not logged in.')
            self.add_message(login_error_message, 'error')
            self.redirect_to('login')

    @webapp2.cached_property
    def form(self):
        if self.is_mobile:
            return forms.EditPasswordMobileForm(self)
        else:
            return forms.EditPasswordForm(self)


class EditEmailHandler(BaseHandler):
    """
    Handler for Edit User's Email
    """

    @user_required
    def get(self):
        """ Returns a simple HTML form for edit email """

        params = {}
        if self.user:
            user_info = models.User.get_by_id(long(self.user_id))
            params['current_email'] = user_info.email

        return self.render_template('edit_email.html', **params)

    def post(self):
        """ Get fields from POST dict """

        if not self.form.validate():
            return self.get()
        new_email = self.form.new_email.data.strip()
        password = self.form.password.data.strip()

        try:
            user_info = models.User.get_by_id(long(self.user_id))
            auth_id = "own:%s" % user_info.username
            # Password to SHA512
            password = utils.hashing(password, self.app.config.get('salt'))

            try:
                # authenticate user by its password
                user = models.User.get_by_auth_password(auth_id, password)

                # if the user change his/her email address
                if new_email != user.email:

                    # check whether the new email has been used by another user
                    aUser = models.User.get_by_email(new_email)
                    if aUser is not None:
                        message = _("The email %s is already registered." % new_email)
                        self.add_message(message, 'error')
                        return self.redirect_to("edit-email")

                    # send email
                    subject = _("%s Email Changed Notification" % self.app.config.get('app_name'))
                    user_token = models.User.create_auth_token(self.user_id)
                    confirmation_url = self.uri_for("email-changed-check",
                        user_id = user_info.get_id(),
                        encoded_email = utils.encode(new_email),
                        token = user_token,
                        _full = True)

                    # load email's template
                    template_val = {
                        "app_name": self.app.config.get('app_name'),
                        "first_name": user.name,
                        "username": user.username,
                        "new_email": new_email,
                        "confirmation_url": confirmation_url,
                        "support_url": self.uri_for("contact", _full=True)
                    }

                    old_body_path = "emails/email_changed_notification_old.txt"
                    old_body = self.jinja2.render_template(old_body_path, **template_val)

                    new_body_path = "emails/email_changed_notification_new.txt"
                    new_body = self.jinja2.render_template(new_body_path, **template_val)

                    email_url = self.uri_for('taskqueue-send-email')
                    taskqueue.add(url = email_url, params={
                        'to': user.email,
                        'subject' : subject,
                        'body' : old_body,
                        })
                    taskqueue.add(url = email_url, params={
                        'to': new_email,
                        'subject' : subject,
                        'body' : new_body,
                        })

                    # display successful message
                    msg = _("Please check your new email for confirmation. Your email will be updated after confirmation.")
                    self.add_message(msg, 'success')
                    return self.redirect_to('edit-profile')

                else:
                    self.add_message(_("You didn't change your email."), "warning")
                    return self.redirect_to("edit-email")


            except (InvalidAuthIdError, InvalidPasswordError), e:
                # Returns error message to self.response.write in
                # the BaseHandler.dispatcher
                message = _("Incorrect password! Please enter your current password to change your account settings.")
                self.add_message(message, 'error')
                return self.redirect_to('edit-email')

        except (AttributeError,TypeError), e:
            login_error_message = _('Sorry you are not logged in.')
            self.add_message(login_error_message,'error')
            self.redirect_to('login')

    @webapp2.cached_property
    def form(self):
        return forms.EditEmailForm(self)


class PasswordResetHandler(BaseHandler):
    """
    Password Reset Handler with Captcha
    """



    def get(self):
        chtml = captcha.displayhtml(
            public_key = self.app.config.get('captcha_public_key'),
            use_ssl = (self.request.scheme == 'https'),
            error = None)
        if self.app.config.get('captcha_public_key') == "PUT_YOUR_RECAPCHA_PUBLIC_KEY_HERE" or \
           self.app.config.get('captcha_private_key') == "PUT_YOUR_RECAPCHA_PUBLIC_KEY_HERE":
            chtml = '<div class="alert alert-error"><strong>Error</strong>: You have to ' \
                    '<a href="http://www.google.com/recaptcha/whyrecaptcha" target="_blank">sign up ' \
                    'for API keys</a> in order to use reCAPTCHA.</div>' \
                    '<input type="hidden" name="recaptcha_challenge_field" value="manual_challenge" />' \
                    '<input type="hidden" name="recaptcha_response_field" value="manual_challenge" />'
        params = {
            'captchahtml': chtml,
            }
        return self.render_template('password_reset.html', **params)

    def post(self):
        # check captcha
        challenge = self.request.POST.get('recaptcha_challenge_field')
        response  = self.request.POST.get('recaptcha_response_field')
        remoteip  = self.request.remote_addr

        cResponse = captcha.submit(
            challenge,
            response,
            self.app.config.get('captcha_private_key'),
            remoteip)

        if cResponse.is_valid:
            # captcha was valid... carry on..nothing to see here
            pass
        else:
            _message = _('Wrong image verification code. Please try again.')
            self.add_message(_message, 'error')
            return self.redirect_to('password-reset')
            #check if we got an email or username
        email_or_username = str(self.request.POST.get('email_or_username')).lower().strip()
        if utils.is_email_valid(email_or_username):
            user = models.User.get_by_email(email_or_username)
            _message = _("If the e-mail address you entered") + " (<strong>%s</strong>) " % email_or_username
        else:
            auth_id = "own:%s" % email_or_username
            user = models.User.get_by_auth_id(auth_id)
            _message = _("If the username you entered") + " (<strong>%s</strong>) " % email_or_username

        _message = _message + _("is associated with an account in our records, you will receive "
                                "an e-mail from us with instructions for resetting your password. "
                                "<br>If you don't receive instructions within a minute or two, "
                                "check your email's spam and junk filters, or ") +\
                   '<a href="' + self.uri_for('contact') + '">' + _('contact us') + '</a> ' +  _("for further assistance.")

        if user is not None:
            user_id = user.get_id()
            token = models.User.create_auth_token(user_id)
            email_url = self.uri_for('taskqueue-send-email')
            reset_url = self.uri_for('password-reset-check', user_id=user_id, token=token, _full=True)
            subject = _("%s Password Assistance" % self.app.config.get('app_name'))

            # load email's template
            template_val = {
                "username": user.username,
                "email": user.email,
                "reset_password_url": reset_url,
                "support_url": self.uri_for("contact", _full=True),
                "app_name": self.app.config.get('app_name'),
            }

            body_path = "emails/reset_password.txt"
            body = self.jinja2.render_template(body_path, **template_val)
            taskqueue.add(url = email_url, params={
                'to': user.email,
                'subject' : subject,
                'body' : body,
                'sender' : self.app.config.get('contact_sender'),
                })
        self.add_message(_message, 'warning')
        return self.redirect_to('login')


class PasswordResetCompleteHandler(BaseHandler):
    """
    Handler to process the link of reset password that received the user
    """

    def get(self, user_id, token):
        verify = models.User.get_by_auth_token(int(user_id), token)
        params = {}
        if verify[0] is None:
            message = _('The URL you tried to use is either incorrect or no longer valid. '
                        'Enter your details again below to get a new one.')
            self.add_message(message, 'warning')
            return self.redirect_to('password-reset')

        else:
            return self.render_template('password_reset_complete.html', **params)

    def post(self, user_id, token):
        verify = models.User.get_by_auth_token(int(user_id), token)
        user = verify[0]
        password = self.form.password.data.strip()
        if user and self.form.validate():
            # Password to SHA512
            password = utils.hashing(password, self.app.config.get('salt'))

            user.password = security.generate_password_hash(password, length=12)
            user.put()
            # Delete token
            models.User.delete_auth_token(int(user_id), token)
            # Login User
            self.auth.get_user_by_password(user.auth_ids[0], password)
            self.add_message(_('Password changed successfully.'), 'success')
            return self.redirect_to('home')

        else:
            self.add_message(_('The two passwords must match.'), 'error')
            return self.redirect_to('password-reset-check', user_id=user_id, token=token)

    @webapp2.cached_property
    def form(self):
        if self.is_mobile:
            return forms.PasswordResetCompleteMobileForm(self)
        else:
            return forms.PasswordResetCompleteForm(self)


class EmailChangedCompleteHandler(BaseHandler):
    """
    Handler for completed email change
    Will be called when the user click confirmation link from email
    """

    def get(self, user_id, encoded_email, token):
        verify = models.User.get_by_auth_token(int(user_id), token)
        email = utils.decode(encoded_email)
        if verify[0] is None:
            message = _('The URL you tried to use is either incorrect or no longer valid.')
            self.add_message(message, 'warning')
            self.redirect_to('home')

        else:
            # save new email
            user = verify[0]
            user.email = email
            user.put()
            # delete token
            models.User.delete_auth_token(int(user_id), token)
            # add successful message and redirect
            message = _('Your email has been successfully updated.')
            self.add_message(message, 'success')
            self.redirect_to('edit-profile')


class HomeRequestHandler(RegisterBaseHandler):
    """
    Handler to show the home page
    """
    """ Age calculator """
    @classmethod
    def ageCal(self, born):
        today = date.today()
        try:
            birthday = born.replace(year=today.year)
        except ValueError: # raised when birth date is February 29 and the current year is not a leap year
            birthday = born.replace(year=today.year, day=born.day-1)
        if birthday > today:
            age = today.year - born.year - 1
        else:
            age = today.year - born.year
        return age

    def get(self):


        """ Returns a simple HTML form for home """
        id_no = 0
        if self.user:
            user_no = models.User.get_by_id(long(self.user_id))
            id_no = user_no.id_no

        cap = models.RandomDaily.get_by_role('captain')
        cap_info = models.User.get_by_id_no(cap.id_No)
        cap_Age = self.ageCal(cap_info.dob)
        cap_country = pycountry.countries.get(alpha2=cap_info.country)
        cap_email = cap_info.email
        cap_imageDisplay= None
        cap_fb = cap_info.facebook
        cap_twit = cap_info.twitter
        cap_link = cap_info.linkedin
        if cap_info.avatar is not None:
            cap_imageDisplay = '<img class="img-circle" width="85px" src="ava?id=' + str(cap_info.id_no) + '">'

        cap_prv = models.Privacy.get_by_id_no(cap_info.id_no)
        if cap_prv.age == False:
            cap_Age = "Undisclosed"
        if cap_prv.country == False:
            cap_country.name = "Undisclosed"
        if cap_prv.email == False:
            cap_email = "Undisclosed"
        if cap_prv.fb == False or cap_fb is None:
            cap_fb = "Undisclosed"
        elif not 'http' in cap_fb:
            cap_fb = "http://" + cap_fb
        if cap_prv.twit == False or cap_twit is None:
            cap_twit = "Undisclosed"
        elif not 'http' in cap_twit:
            cap_twit = "http://" + cap_twit
        if cap_prv.link == False or cap_link is None:
            cap_link = "Undisclosed"
        elif not 'http' in cap_link:
            cap_link = "http://" + cap_link


        crew1 = models.RandomDaily.get_by_role('crew1')
        crew1_info = models.User.get_by_id_no(crew1.id_No)
        crew1_Age = self.ageCal(crew1_info.dob)
        crew1_email = crew1_info.email
        crew1_country = pycountry.countries.get(alpha2=crew1_info.country)
        crew1_imageDisplay= None
        crew1_fb = crew1_info.facebook
        crew1_twit = crew1_info.twitter
        crew1_link = crew1_info.linkedin
        if crew1_info.avatar is not None:
            crew1_imageDisplay = '<img class="img-circle" width="85px" src="ava?id=' + str(crew1_info.id_no) + '">'
        crew1_prv = models.Privacy.get_by_id_no(crew1_info.id_no)
        if crew1_prv.age == False:
            crew1_Age = "Undisclosed"
        if crew1_prv.country == False:
            crew1_country.name = "Undisclosed"
        if crew1_prv.email == False:
            crew1_email = "Undisclosed"
        if crew1_prv.fb == False or crew1_fb is None:
            crew1_fb = "Undisclosed"
        elif not 'http' in crew1_fb:
            crew1_fb = "http://" + crew1_fb
        if crew1_prv.twit == False or crew1_twit is None:
            crew1_twit = "Undisclosed"
        elif not 'http' in crew1_twit:
            crew1_twit = "http://" + crew1_twit
        if crew1_prv.link == False or crew1_link is None:
            crew1_link = "Undisclosed"
        elif not 'http' in crew1_link:
            crew1_link = "http://" + crew1_link

        crew2 = models.RandomDaily.get_by_role('crew2')
        crew2_info = models.User.get_by_id_no(crew2.id_No)
        crew2_Age = self.ageCal(crew2_info.dob)
        crew2_email = crew2_info.email
        crew2_country = pycountry.countries.get(alpha2=crew2_info.country)
        crew2_fb = crew2_info.facebook
        crew2_twit = crew2_info.twitter
        crew2_link = crew2_info.linkedin
        crew2_imageDisplay= None
        if crew2_info.avatar is not None:
            crew2_imageDisplay = '<img class="img-circle" width="85px" src="ava?id=' + str(crew2_info.id_no) + '">'
        crew2_prv = models.Privacy.get_by_id_no(crew2_info.id_no)
        if crew2_prv.age == False:
            crew2_Age = "Undisclosed"
        if crew2_prv.country == False:
            crew2_country.name = "Undisclosed"
        if crew2_prv.email == False:
            crew2_email = "Undisclosed"
        if crew2_prv.fb == False or crew2_fb is None:
            crew2_fb = "Undisclosed"
        elif not 'http' in crew2_fb:
            crew2_fb = "http://" + crew2_fb
        if crew2_prv.twit == False or crew2_twit is None:
            crew2_twit = "Undisclosed"
        elif not 'http' in crew2_twit:
            crew2_twit = "http://" + crew2_twit
        if crew2_prv.link == False or crew2_link is None:
            crew2_link = "Undisclosed"
        elif not 'http' in crew2_link:
            crew2_link = "http://" + crew2_link

        crew3 = models.RandomDaily.get_by_role('crew3')
        crew3_info = models.User.get_by_id_no(crew3.id_No)
        crew3_Age = self.ageCal(crew3_info.dob)
        crew3_email = crew3_info.email
        crew3_country = pycountry.countries.get(alpha2=crew3_info.country)
        crew3_fb = crew3_info.facebook
        crew3_twit = crew3_info.twitter
        crew3_link = crew3_info.linkedin
        crew3_imageDisplay= None
        if crew3_info.avatar is not None:
            crew3_imageDisplay = '<img class="img-circle" width="85px" src="ava?id=' + str(crew3_info.id_no) + '">'
        crew3_prv = models.Privacy.get_by_id_no(crew3_info.id_no)
        if crew3_prv.age == False:
            crew3_Age = "Undisclosed"
        if crew3_prv.country == False:
            crew3_country.name = "Undisclosed"
        if crew3_prv.email == False:
            crew3_email = "Undisclosed"
        if crew3_prv.fb == False or crew3_fb is None:
            crew3_fb = "Undisclosed"
        elif not 'http' in crew3_fb:
            crew3_fb = "http://" + crew3_fb
        if crew3_prv.twit == False or crew3_twit is None:
            crew3_twit = "Undisclosed"
        elif not 'http' in crew3_twit:
            crew3_twit = "http://" + crew3_twit
        if crew3_prv.link == False or crew3_link is None:
            crew3_link = "Undisclosed"
        elif not 'http' in crew3_link:
            crew3_link = "http://" + crew3_link

        crew4 = models.RandomDaily.get_by_role('crew4')
        crew4_info = models.User.get_by_id_no(crew4.id_No)
        crew4_Age = self.ageCal(crew4_info.dob)
        crew4_email = crew4_info.email
        crew4_country = pycountry.countries.get(alpha2=crew4_info.country)
        crew4_fb = crew4_info.facebook
        crew4_twit = crew4_info.twitter
        crew4_link = crew4_info.linkedin
        crew4_imageDisplay= None
        if crew4_info.avatar is not None:
            crew4_imageDisplay = '<img class="img-circle" width="85px" src="ava?id=' + str(crew4_info.id_no) + '">'
        crew4_prv = models.Privacy.get_by_id_no(crew4_info.id_no)
        if crew4_prv.age == False:
            crew4_Age = "Undisclosed"
        if crew4_prv.country == False:
            crew4_country.name = "Undisclosed"
        if crew4_prv.email == False:
            crew4_email = "Undisclosed"
        if crew4_prv.fb == False or crew4_fb is None:
            crew4_fb = "Undisclosed"
        elif not 'http' in crew4_fb:
            crew4_fb = "http://" + crew4_fb
        if crew4_prv.twit == False or crew4_twit is None:
            crew4_twit = "Undisclosed"
        elif not 'http' in crew4_twit:
            crew4_twit = "http://" + crew4_twit
        if crew4_prv.link == False or crew4_link is None:
            crew4_link = "Undisclosed"
        elif not 'http' in crew4_link:
            crew4_link = "http://" + crew4_link

        template_values = {
        'name': cap_info.name, 'country': cap_country.name, 'pm': cap_info.pm, 'occupation': cap_info.occupation,
        'age': cap_Age, 'contribution': cap_info.contribution, 'imageD': cap_imageDisplay, 'email_cap' : cap_email,
        'cap_fb' : cap_fb, 'cap_twit': cap_twit, 'cap_link': cap_link,

        'name1': crew1_info.name, 'country1': crew1_country.name, 'pm1': crew1_info.pm, 'occupation1': crew1_info.occupation,
        'age1': crew1_Age, 'contribution1': crew1_info.contribution, 'imageD1': crew1_imageDisplay, 'email1' : crew1_email,
        'crew1_fb' : crew1_fb, 'crew1_twit': crew1_twit, 'crew1_link': crew1_link,

        'name2': crew2_info.name, 'country2': crew2_country.name, 'pm2': crew2_info.pm, 'occupation2': crew2_info.occupation,
        'age2': crew2_Age, 'contribution2': crew2_info.contribution, 'imageD2': crew2_imageDisplay, 'email2' : crew2_email,
        'crew2_fb' : crew2_fb, 'crew2_twit': crew2_twit, 'crew2_link': crew2_link,

        'name3': crew3_info.name, 'country3': crew3_country.name, 'pm3': crew3_info.pm, 'occupation3': crew3_info.occupation,
        'age3': crew3_Age, 'contribution3': crew3_info.contribution, 'imageD3': crew3_imageDisplay, 'email3' : crew3_email,
        'crew3_fb' : crew3_fb, 'crew3_twit': crew3_twit, 'crew3_link': crew3_link,

        'name4': crew4_info.name, 'country4': crew4_country.name, 'pm4': crew4_info.pm, 'occupation4': crew4_info.occupation,
        'age4': crew4_Age, 'contribution4': crew4_info.contribution, 'imageD4': crew4_imageDisplay, 'email4' : crew4_email,
        'crew4_fb' : crew4_fb, 'crew4_twit': crew4_twit, 'crew4_link': crew4_link,

        'occ': '/discover',

        'user_no': id_no
        }


        return self.render_template('random.html', **template_values)

class RandomRequestHandler(RegisterBaseHandler):
    """
    Handler to show the home page
    """
    """ Age calculator """
    @classmethod
    def ageCal(self, born):
        today = date.today()
        try:
            birthday = born.replace(year=today.year)
        except ValueError: # raised when birth date is February 29 and the current year is not a leap year
            birthday = born.replace(year=today.year, day=born.day-1)
        if birthday > today:
            age = today.year - born.year - 1
        else:
            age = today.year - born.year
        return age

    def get(self):
        """ Returns a simple HTML form for home """
        id_no = 0
        if self.user:
            user_no = models.User.get_by_id(long(self.user_id))
            id_no = user_no.id_no

        while 1==1:
            randNo = random.randint(1, models.User.id_gen())
            user_info = models.User.get_by_id_no(randNo)
            if user_info is not None and user_info.activated == True:
                break

        user_info = models.User.get_by_id_no(randNo) #to change
        age = self.ageCal(user_info.dob)
        country = pycountry.countries.get(alpha2=user_info.country) #country code convertor
        cap_fb = user_info.facebook
        cap_twit = user_info.twitter
        cap_link = user_info.linkedin
        """ Avatar display """
        imageDisplay= None
        if user_info.avatar is not None:
            imageDisplay = '<img class="img-circle" src="/ava?id=' + str(user_info.id_no) + '">'

        user_prv = models.Privacy.get_by_id_no(user_info.id_no)
        if user_prv.age == False:
            age = "Undisclosed"
        if user_prv.country == False:
            country.name = "Undisclosed"
        if user_prv.email == False:
            email = "Undisclosed"
        else:
            email = user_info.email
        if user_prv.fb == False or cap_fb is None:
            cap_fb = "Undisclosed"
        elif not 'http' in cap_fb:
            cap_fb = "http://" + cap_fb
        if user_prv.twit == False or cap_twit is None:
            cap_twit = "Undisclosed"
        elif not 'http' in cap_twit:
            cap_twit = "http://" + cap_twit
        if user_prv.link == False or cap_link is None:
            cap_link = "Undisclosed"
        elif not 'http' in cap_link:
            cap_link = "http://" + cap_link

        template_values = {
        'name': user_info.name, 'country': country.name, 'pm': user_info.pm, 'occupation': user_info.occupation,
        'age': age, 'contribution': user_info.contribution, 'avatar': user_info.avatar,
        'id': user_info.id_no, 'imageD': imageDisplay, 'email_cap' : email, 'user_no': id_no,
        'cap_fb' : cap_fb, 'cap_twit': cap_twit, 'cap_link': cap_link
        }
        return self.render_template('lucky.html', **template_values)

class RandomScheduledRequestHandler(RegisterBaseHandler):
    """
        Random number generator based on id. id upper limit is determine by a count of the number of row in datastore
        limitation: If user is deleted, id may higher than the upper limit (determine by count)
    """
    @classmethod
    def randomer(self):
        counter = 0
        while counter<=100: #prevent infinite loop
            randNo = random.randint(1, models.User.id_gen())

            user_info = models.User.get_by_id_no(randNo)
            if user_info is not None and user_info.activated == True:
                break
            counter += 1
        return randNo

    """
        check whether number is unique or not
    """
    @classmethod
    def unique_checker(self, itemList):
        number=self.randomer()
        unique=False
        while unique==False:
            unique=True
            for item in itemList:
                if item == number:
                    unique=False
                    number = self.randomer()
                    break
        return number

    """
        Pre:    Database must contain at least 5 user.
                User id must be sequestial
                No deletion of user
    """
    def get(self):
        used_no = []

        if models.RandomDaily.count() != 5:
            number=self.randomer()
            cap = models.RandomDaily(role='captain',
                id_No=number)
            cap.put()

            used_no.append(number)
            number = self.unique_checker(used_no)
            crew1 = models.RandomDaily(role='crew1',
                id_No=number)
            crew1.put()

            used_no.append(number)
            number = self.unique_checker(used_no)
            crew2 = models.RandomDaily(role='crew2',
                id_No=number)
            crew2.put()

            used_no.append(number)
            number = self.unique_checker(used_no)
            crew3 = models.RandomDaily(role='crew3',
                id_No=number)
            crew3.put()

            used_no.append(number)
            number = self.unique_checker(used_no)
            crew4 = models.RandomDaily(role='crew4',
                id_No=number)
            crew4.put()
        else:
            number=self.randomer()
            cap = models.RandomDaily.get_by_role('captain')
            cap.id_No=number
            cap.put()

            used_no.append(number)
            number = self.unique_checker(used_no)
            c1 = models.RandomDaily.get_by_role('crew1')
            c1.id_No = number
            c1.put()

            used_no.append(number)
            number = self.unique_checker(used_no)
            c2 = models.RandomDaily.get_by_role('crew2')
            c2.id_No = number
            c2.put()

            used_no.append(number)
            number = self.unique_checker(used_no)
            c3 = models.RandomDaily.get_by_role('crew3')
            c3.id_No = number
            c3.put()

            used_no.append(number)
            number = self.unique_checker(used_no)
            c4 = models.RandomDaily.get_by_role('crew4')
            c4.id_No = number
            c4.put()

        params = {}
        return self.render_template('errors/forbidden_access.html', **params)


    def post(self):
        """ Get fields from POST dict """

        if not self.form.validate():
            return self.get()
        username = self.form.username.data.lower()
        name = self.form.name.data.strip()
        last_name = self.form.last_name.data.strip()
        email = self.form.email.data.lower()
        password = self.form.password.data.strip()
        country = self.form.country.data
        occupation = self.form.occupation.data
        contribution = self.form.contribution.data
        pm = self.form.pm.data
        dob = self.form.dob.data
        id_no = models.User.id_gen() + 1
        # Password to SHA512
        password = utils.hashing(password, self.app.config.get('salt'))
        avatar = self.request.get('avatar')

        # Passing password_raw=password so password will be hashed
        # Returns a tuple, where first value is BOOL.
        # If True ok, If False no new user is created
        unique_properties = ['username', 'email']
        auth_id = "own:%s" % username
        user = self.auth.store.user_model.create_user(
            auth_id, unique_properties, password_raw=password,
            username=username, name=name, last_name=last_name, email=email,
            ip=self.request.remote_addr, country=country, occupation=occupation,
            contribution=contribution, pm=pm, dob=dob, id_no=id_no
        )
        #privacy = self.auth.store.user_model.create_user(
        #    country=True, country=True, dob=True
        #)

        if not user[0]: #user is a tuple
            if "username" in str(user[1]):
                message = _('Sorry, The username %s is already registered.' % '<strong>{0:>s}</strong>'.format(username) )
            elif "email" in str(user[1]):
                message = _('Sorry, The email %s is already registered.' % '<strong>{0:>s}</strong>'.format(email) )
            else:
                message = _('Sorry, The user is already registered.')
            self.add_message(message, 'error')
            return self.redirect_to('register')
        else:
            # User registered successfully
            # But if the user registered using the form, the user has to check their email to activate the account ???
            try:

                time.sleep(0.5)
                user_info = models.User.get_by_email(email)
                try:
                    user_info.avatar = db.Blob(avatar)
                    user_info.put()
                except:
                    pass

                if (user_info.activated == False):
                    # send email
                    subject =  _("%s Account Verification" % self.app.config.get('app_name'))
                    confirmation_url = self.uri_for("account-activation",
                        user_id=user_info.get_id(),
                        token = models.User.create_auth_token(user_info.get_id()),
                        _full = True)

                    # load email's template
                    template_val = {
                        "app_name": self.app.config.get('app_name'),
                        "username": username,
                        "confirmation_url": confirmation_url,
                        "support_url": self.uri_for("contact", _full=True)
                    }
                    body_path = "emails/account_activation.txt"
                    body = self.jinja2.render_template(body_path, **template_val)

                    email_url = self.uri_for('taskqueue-send-email')
                    taskqueue.add(url = email_url, params={
                        'to': str(email),
                        'subject' : subject,
                        'body' : body,
                        })

                    message = _('You were successfully registered. '
                                'Please check your email to activate your account. ' )
                    self.add_message(message, 'success')
                    return self.redirect_to('home')

                # If the user didn't register using registration form ???
                db_user = self.auth.get_user_by_password(user[1].auth_ids[0], password)
                # Check twitter association in session
                twitter_helper = twitter.TwitterAuth(self)
                twitter_association_data = twitter_helper.get_association_data()
                if twitter_association_data is not None:
                    if models.SocialUser.check_unique(user[1].key, 'twitter', str(twitter_association_data['id'])):
                        social_user = models.SocialUser(
                            user = user[1].key,
                            provider = 'twitter',
                            uid = str(twitter_association_data['id']),
                            extra_data = twitter_association_data
                        )
                        social_user.put()

                #check facebook association
                fb_data = json.loads(self.session['facebook'])

                if fb_data is not None:
                    if models.SocialUser.check_unique(user.key, 'facebook', str(fb_data['id'])):
                        social_user = models.SocialUser(
                            user = user.key,
                            provider = 'facebook',
                            uid = str(fb_data['id']),
                            extra_data = fb_data
                        )
                        social_user.put()
                #check linkedin association
                li_data = json.loads(self.session['linkedin'])
                if li_data is not None:
                    if models.SocialUser.check_unique(user.key, 'linkedin', str(li_data['id'])):
                        social_user = models.SocialUser(
                            user = user.key,
                            provider = 'linkedin',
                            uid = str(li_data['id']),
                            extra_data = li_data
                        )
                        social_user.put()


                message = _('Welcome %s, you are now logged in.' % '<strong>{0:>s}</strong>'.format(username) )
                self.add_message(message, 'success')
                return self.redirect_to('home')
            except (AttributeError, KeyError), e:
                logging.error('Unexpected error creating the user %s: %s' % (username, e ))
                message = _('Unexpected error creating the user %s' % username )
                #message = _('Unexpected error creating the user %s' % username )
                self.add_message(message, 'error')
                return self.redirect_to('home')

class GetImage(RegisterBaseHandler):
    def get(self):
        idno = int(self.request.get("id"))
        user_info = models.User.get_by_id_no(idno)

        if user_info.avatar:
            self.response.headers['Content-Type'] = "image/png"
            self.response.out.write(user_info.avatar)

class ContactEndRequestHandler(RegisterBaseHandler):
    """
    Handler to show the home page
    """

    def get(self):
        """ Returns a simple HTML form for home """
        params = {}
        return self.render_template('thankyou.html', **params)

class userProfileHandler(RegisterBaseHandler):
    """
    Handler to control user profile
    """

    """
    Handler to show the home page
    """
    """ Age calculator """
    @classmethod
    def ageCal(self, born):
        today = date.today()
        try:
            birthday = born.replace(year=today.year)
        except ValueError: # raised when birth date is February 29 and the current year is not a leap year
            birthday = born.replace(year=today.year, day=born.day-1)
        if birthday > today:
            age = today.year - born.year - 1
        else:
            age = today.year - born.year
        return age

    def get(self):
        id_no = 0
        if self.user:
            user_no = models.User.get_by_id(long(self.user_id))
            id_no = user_no.id_no


        try:
            idno = int(self.request.get("id"))
            user_info = models.User.get_by_id_no(idno)

            if user_info is None:
                self.redirect("home")

            #user_info = models.User.get_by_id_no(1)
            age = self.ageCal(user_info.dob)
            country = pycountry.countries.get(alpha2=user_info.country) #country code convertor
            cap_fb = user_info.facebook
            cap_twit = user_info.twitter
            cap_link = user_info.linkedin
            """ Avatar display """
            imageDisplay= None
            if user_info.avatar is not None:
                imageDisplay = '<img class="img-circle" src="/ava?id=' + str(user_info.id_no) + '">'

            user_prv = models.Privacy.get_by_id_no(user_info.id_no)
            if user_prv.age == False:
                age = "Undisclosed"
            if user_prv.country == False:
                country.name = "Undisclosed"
            if user_prv.email == False:
                email = "Undisclosed"
            else:
                email = user_info.email
            if user_prv.fb == False or cap_fb is None:
                cap_fb = "Undisclosed"
            elif not 'http' in cap_fb:
                cap_fb = "http://" + cap_fb
            if user_prv.twit == False or cap_twit is None:
                cap_twit = "Undisclosed"
            elif not 'http' in cap_twit:
                cap_twit = "http://" + cap_twit
            if user_prv.link == False or cap_link is None:
                cap_link = "Undisclosed"
            elif not 'http' in cap_link:
                cap_link = "http://" + cap_link

            template_values = {
            'name': user_info.name, 'country': country.name, 'pm': user_info.pm, 'occupation': user_info.occupation,
            'age': age, 'contribution': user_info.contribution, 'avatar': user_info.avatar,
            'id': user_info.id_no, 'imageD': imageDisplay, 'email_cap' : email,  'user_no': id_no,
            'cap_fb' : cap_fb, 'cap_twit': cap_twit, 'cap_link': cap_link,
            }
            return self.render_template('user.html', **template_values)
        except (AttributeError, TypeError, ValueError), e:
            logging.error('Error updating privacy setting: ' + str(e))
            login_error_message = _('Sorry no such user exists.')
            self.add_message(login_error_message, 'error')
            self.redirect_to('home')

class privacyHandler(RegisterBaseHandler):
    #"MAY"need user_required and change to basehandler

    def get(self):

        params = {}
        if self.user:
            user_info = models.User.get_by_id(long(self.user_id))
            user_obj = models.Privacy.get_by_id_no(user_info.id_no)
            self.form.p_email.data = user_obj.email
            self.form.p_country.data = user_obj.country
            self.form.p_dob.data = user_obj.age
            self.form.p_fb.data = user_obj.fb
            self.form.p_twit.data = user_obj.twit
            self.form.p_link.data = user_obj.link

            providers_info = user_info.get_social_providers_info()
            if not user_info.password:
                params['local_account'] = False
            else:
                params['local_account'] = True
            params['used_providers'] = providers_info['used']
            params['unused_providers'] = providers_info['unused']
            params['country'] = user_info.country

        return self.render_template('privacy.html', **params)

    def post(self):
        """ Get fields from POST dict """

        #if not self.form.validate():
        #    return self.get()
        p_email = self.form.p_email.data
        p_country = self.form.p_country.data
        p_age = self.form.p_dob.data
        p_fb = self.form.p_fb.data
        p_twit = self.form.p_twit.data
        p_link = self.form.p_link.data

        try:
            user_info = models.User.get_by_id(long(self.user_id))
            user_obj = models.Privacy.get_by_id_no(user_info.id_no)

            if(user_obj == None):
                login_error_message = _('Sorry you are not logged in.')
                self.add_message(login_error_message, 'error')
                #self.redirect_to('login')
                self.redirect_to('privacy')

            try:
                message=''
                user_obj.country  = p_country
                user_obj.age = p_age
                user_obj.email = p_email
                user_obj.fb = p_fb
                user_obj.twit = p_twit
                user_obj.link = p_link
                user_obj.put()

                message+= " " + _('Thanks, your privacy settings have been saved.')
                self.add_message(message, 'success')
                self.redirect_to('privacy')
                #return self.get()

            except (AttributeError, KeyError, ValueError), e:
                logging.error('Error updating settings: ' + e)
                message = _('Unable to update settings. Please try again later.')
                self.add_message(message, 'error')
                self.redirect_to('privacy')
                #return self.get()

        except (AttributeError, TypeError), e:
            logging.error('Error updating privacy setting: ' + str(e))
            login_error_message = _('Sorry you are not logged in.')
            self.add_message(login_error_message, 'error')
            #self.redirect_to('login')
            self.redirect_to('privacy')

class discoverHandler(RegisterBaseHandler):
    """
    Handler to control occupation discovery feature
    """

    """
    Handler to show the home page
    """
    """ Age calculator """
    @classmethod
    def ageCal(self, born):
        today = date.today()
        try:
            birthday = born.replace(year=today.year)
        except ValueError: # raised when birth date is February 29 and the current year is not a leap year
            birthday = born.replace(year=today.year, day=born.day-1)
        if birthday > today:
            age = today.year - born.year - 1
        else:
            age = today.year - born.year
        return age

    def get(self):
        id_no = 0
        if self.user:
            user_no = models.User.get_by_id(long(self.user_id))
            id_no = user_no.id_no


        occ_title = self.request.get("occ")
        occ_count = models.User.count_by_occ(occ_title)
        if occ_count is not 0:
            randNo=0
            while 1==1:
                randNo = random.randint(1, occ_count)
                user_info = models.User.get_by_id_no(randNo)
                if user_info is not None and user_info.activated == True:
                    break
            user_info = models.User.return_by_occ(randNo-1, occ_title)

            i = iter(user_info)
            user_info = i.next()

            age = self.ageCal(user_info.dob)
            country = pycountry.countries.get(alpha2=user_info.country) #country code convertor
            email = user_info.email
            cap_fb = user_info.facebook
            cap_twit = user_info.twitter
            cap_link = user_info.linkedin
            """ Avatar display """
            imageDisplay= None
            if user_info.avatar is not None:
                imageDisplay = '<img class="img-circle" src="/ava?id=' + str(user_info.id_no) + '">'

            user_prv = models.Privacy.get_by_id_no(user_info.id_no)
            if user_prv.age == False:
                age = "Undisclosed"
            if user_prv.country == False:
                country.name = "Undisclosed"
            if user_prv.email == False:
                email = "Undisclosed"
            if user_prv.fb == False or cap_fb is None:
                cap_fb = "Undisclosed"
            elif not 'http' in cap_fb:
                cap_fb = "http://" + cap_fb
            if user_prv.twit == False or cap_twit is None:
                cap_twit = "Undisclosed"
            elif not 'http' in cap_twit:
                cap_twit = "http://" + cap_twit
            if user_prv.link == False or cap_link is None:
                cap_link = "Undisclosed"
            elif not 'http' in cap_link:
                cap_link = "http://" + cap_link

            template_values = {
            'name': user_info.name, 'country': country.name, 'pm': user_info.pm, 'occupation': user_info.occupation,
            'age': age, 'contribution': user_info.contribution, 'avatar': user_info.avatar,
            'id': user_info.id_no, 'imageD': imageDisplay, 'email_cap' : email, 'user_no': id_no,
            'cap_fb' : cap_fb, 'cap_twit': cap_twit, 'cap_link': cap_link
            }
            return self.render_template('lucky.html', **template_values)
        else:
            login_error_message = _('Sorry, there is no result.')
            self.add_message(login_error_message, 'error')
            self.redirect_to('home')

class searchDiscoverHandler(RegisterBaseHandler):
    """
    Handler to search by occupation
    Redirect via get to /discover
    """
    def get(self):
        params = {'occ': '/discover'}
        return self.render_template('random.html', **params)



