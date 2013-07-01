"""
This is the boilerplate default configuration file.
Changes and additions to settings should be done in the config module
located in the application root rather than this config.
"""
config = {

# webapp2 sessions
'webapp2_extras.sessions' : {'secret_key': '_PUT_KEY_HERE_YOUR_SECRET_KEY_'},

# webapp2 authentication
'webapp2_extras.auth' : {'user_model': 'boilerplate.models.User',
                         'cookie_name': 'session_name'},

# jinja2 templates
'webapp2_extras.jinja2' : {'template_path': ['templates','boilerplate/templates', 'admin/templates'],
                           'environment_args': {'extensions': ['jinja2.ext.i18n']}},

# application name
'app_name' : "The Arky",

# the default language code for the application.
# should match whatever language the site uses when i18n is disabled
'app_lang' : 'en',

# Locale code = <language>_<territory> (ie 'en_US')
# to pick locale codes see http://cldr.unicode.org/index/cldr-spec/picking-the-right-language-code
# also see http://www.sil.org/iso639-3/codes.asp
# Language codes defined under iso 639-1 http://en.wikipedia.org/wiki/List_of_ISO_639-1_codes
# Territory codes defined under iso 3166-1 alpha-2 http://en.wikipedia.org/wiki/ISO_3166-1
# disable i18n if locales array is empty or None
'locales' : ['en_US', 'es_ES', 'it_IT', 'zh_CN', 'id_ID', 'fr_FR', 'de_DE', 'ru_RU', 'pt_BR', 'cs_CZ'],

# contact page email settings
'contact_sender' : "PUT_SENDER_EMAIL_HERE",
'contact_recipient' : "PUT_RECIPIENT_EMAIL_HERE",

# Password AES Encryption Parameters
'aes_key' : "12_24_32_BYTES_KEY_FOR_PASSWORDS",
'salt' : "_PUT_SALT_HERE_TO_SHA512_PASSWORDS_",

# get your own consumer key and consumer secret by registering at https://dev.twitter.com/apps
# callback url must be: http://[YOUR DOMAIN]/login/twitter/complete
'twitter_consumer_key' : 'wBtHqd4a3IqZN89J1TCeog',
'twitter_consumer_secret' : 'aH9isB1ZI2zM8gYMWrEhOI2DQaCXhn59PQCdyheMg',

#Facebook Login
# get your own consumer key and consumer secret by registering at https://developers.facebook.com/apps
#Very Important: set the site_url= your domain in the application settings in the facebook app settings page
# callback url must be: http://[YOUR DOMAIN]/login/facebook/complete
'fb_api_key' : '136496959884393',
'fb_secret' : '70623320f6537fec08eb4a308ddc54b9',

#Linkedin Login
#Get you own api key and secret from https://www.linkedin.com/secure/developer
'linkedin_api' : 'xv9iudz1frb8',
'linkedin_secret' : 'lPdAnwbrlOFViozl',

# Github login
# Register apps here: https://github.com/settings/applications/new
'github_server' : 'github.com',
'github_redirect_uri' : 'http://www.example.com/social_login/github/complete',
'github_client_id' : 'bf270aa784452945c2d9',
'github_client_secret' : '9e80bd5c451605437dbffb03e22af4036d8d645f',

# get your own recaptcha keys by registering at http://www.google.com/recaptcha/
'captcha_public_key' : "6Lf3-uISAAAAAJJmMkUjTP_Pjg7iXCVadduKEbl2",
'captcha_private_key' : "6Lf3-uISAAAAAFxZOHfmSw2Kydxfk6K_vOfXP5rW",

# Leave blank "google_analytics_domain" if you only want Analytics code
'google_analytics_domain' : "YOUR_PRIMARY_DOMAIN (e.g. google.com)",
'google_analytics_code' : "UA-XXXXX-X",

# add status codes and templates used to catch and display errors
# if a status code is not listed here it will use the default app engine
# stacktrace error page or browser error page
'error_templates' : {
    403: 'errors/default_error.html',
    404: 'errors/default_error.html',
    500: 'errors/default_error.html',
},

# Enable Federated login (OpenID and OAuth)
# Google App Engine Settings must be set to Authentication Options: Federated Login
'enable_federated_login' : True,

# jinja2 base layout template
'base_layout' : 'base.html',

# send error emails to developers
'send_mail_developer' : False,

# fellas' list
'developers' : (
    ('Tan Jun Hao', 'bb111189@gmail.com')
),

# If true, it will write in datastore a log of every email sent
'log_email' : False,

# If true, it will write in datastore a log of every visit
'log_visit' : False,

# ----> ADD MORE CONFIGURATION OPTIONS HERE <----

} # end config
