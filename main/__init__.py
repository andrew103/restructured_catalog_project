from flask import Flask, jsonify, request, g, make_response
from flask import url_for, redirect, flash

from flask import render_template as flask_render

from .models import Base, User, Category, Item
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from functools import wraps

from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError

from flask import session as login_session
import random, string, json, httplib2, requests

import flask_login
from flask_login import LoginManager, login_user

import sys

#===================== INIT CODE ============================

CLIENT_ID = json.loads(open('/var/www/catalog/main/client_secrets.json', 'r').read())['web']['client_id']

engine = create_engine('postgresql://catalog:database@localhost/catalogdb')
Base.metadata.bind = engine
DBSession = sessionmaker(bind=engine)
session = DBSession()

app = Flask(__name__)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

app.secret_key = "catalogapplication"
app.debug = True

# ================= BEGIN LOGIN REQUIREMENT CODE ==============

@login_manager.user_loader
def load_user(user_id):
    '''
    Takes a unicode format user id and uses it to retrieve the respective user
    object to be used by the login_manager
    '''
    user = session.query(User).filter_by(id=int(user_id)).first()
    return user

# ================== END LOGIN REQUIREMENT CODE ===============

#=================== BEGIN THIRD PARTY LOGIN CODE =============

@app.route('/fbconnect', methods=['POST'])
def fbconnect():
    '''
    Facebook API code to allow for a user to login to the site using their
    Facebook account
    '''
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    access_token = request.data.decode('utf-8')
    print ("access token received %s " % access_token)


    app_id = json.loads(open('/var/www/catalog/main/fb_client_secrets.json', 'r').read())[
        'web']['app_id']
    app_secret = json.loads(
        open('/var/www/catalog/main/fb_client_secrets.json', 'r').read())['web']['app_secret']
    url = 'https://graph.facebook.com/oauth/access_token?grant_type=fb_exchange_token&client_id=%s&client_secret=%s&fb_exchange_token=%s' % (
        app_id, app_secret, access_token)
    h = httplib2.Http()
    result = h.request(url, 'GET')[1].decode('utf-8')


    # Use token to get user info from API
    userinfo_url = "https://graph.facebook.com/v2.8/me"
    '''
        Due to the formatting for the result from the server token exchange we have to
        split the token first on commas and select the first index which gives us the key : value
        for the server access token then we split it on colons to pull out the actual token value
        and replace the remaining quotes with nothing so that it can be used directly in the graph
        api calls
    '''
    token = result.split(',')[0].split(':')[1].replace('"', '')

    url = 'https://graph.facebook.com/v2.8/me?access_token=%s&fields=name,id,email' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1].decode('utf-8')
    # print "url sent for API access:%s"% url
    # print "API JSON result: %s" % result
    data = json.loads(result)

    print(data, file=sys.stdout)

    login_session['provider'] = 'facebook'
    login_session['username'] = data["name"]
    login_session['email'] = data["email"]
    login_session['facebook_id'] = data["id"]

    # The token must be stored in the login_session in order to properly logout
    login_session['access_token'] = token

    # Get user picture
    url = 'https://graph.facebook.com/v2.8/me/picture?access_token=%s&redirect=0&height=200&width=200' % token
    h = httplib2.Http()
    result = h.request(url, 'GET')[1].decode('utf-8')
    data = json.loads(result)

    # see if user exists
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    user = session.query(User).filter_by(email=login_session['email']).one()
    login_user(user)
    user.is_authenticated = True


    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'

    flash("Now logged in as %s" % login_session['username'])
    return output


@app.route('/fbdisconnect')
def fbdisconnect():
    '''
    Disconnects a user's Facebook account when they log out
    '''
    facebook_id = login_session['facebook_id']
    # The access token must me included to successfully logout
    access_token = login_session['access_token']
    url = 'https://graph.facebook.com/%s/permissions?access_token=%s' % (facebook_id,access_token)
    h = httplib2.Http()
    result = h.request(url, 'DELETE')[1].decode('utf-8')
    return "you have been logged out"


@app.route('/gconnect', methods=['POST'])
def gconnect():
    '''
    Google API code to allow for a user to login to the site using their
    Google account
    '''

    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('/var/www/catalog/main/client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1].decode('utf-8'))
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print ("Token's client ID does not match app's.")
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_credentials = login_session.get('credentials')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_credentials is not None and gplus_id == stored_gplus_id:
        response = make_response(json.dumps('Current user is already connected.'),
                                 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['email'] = data['email']
    # ADD PROVIDER TO LOGIN SESSION
    login_session['provider'] = 'google'

    # see if user exists, if it doesn't make a new one
    user_id = getUserID(data["email"])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    user = session.query(User).filter_by(email=login_session['email']).one()
    login_user(user)
    user.is_authenticated = True



    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'

    flash("you are now logged in as %s" % login_session['username'])
    return output


# Helper functions to help connect the third party login APIs with the User
# database object
def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None


@app.route('/gdisconnect')
def gdisconnect():
    '''
    Disconnects a user's Google account when they log out
    '''
    # Only disconnect a connected user.
    credentials = login_session.get('credentials')
    if credentials is None:
        response = make_response(
            json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    access_token = credentials.access_token
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % access_token
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    if result['status'] != '200':
        # For whatever reason, the given token was invalid.
        response = make_response(
            json.dumps('Failed to revoke token for given user.'), 400)
        response.headers['Content-Type'] = 'application/json'
        return response

#=================== END THIRD PARTY LOGIN CODE ===============

#=================== BEGIN TEMPLATE RENDERING ENGINE ==========

def render_template(template_name, **params):
    params['categories'] = session.query(Category).all()
    params['current_user'] = flask_login.current_user
    return flask_render(template_name, **params)

#=================== END TEMPLATE RENDERING ENGINE ============

#=================== BEGIN USER CHECK CODE ====================

def user_check(object):
    if object.user_id == flask_login.current_user.id:
        return True
    return False

#=================== END USER CHECK CODE ======================

#=================== BEGIN JSON FORMATTED PAGES ===============

@app.route('/catalog/json')
def jsonCatalog():
    categories = session.query(Category).all()
    return jsonify(Categories=[i.serialize for i in categories])


@app.route('/catalog/<string:cat_name>/json')
@app.route('/catalog/<string:cat_name>/items/json')
def jsonCatItems(cat_name):
    catitems = session.query(Item).filter_by(cat_name=cat_name).all()
    return jsonify(CatItems=[i.serialize for i in catitems])


@app.route('/catalog/<string:cat_name>/<string:item_name>/json')
def jsonItem(cat_name, item_name):
    item = session.query(Item).filter_by(name=item_name).one()
    return jsonify(Item=item.serialize)

#================== END JSON FORMATTED PAGES ==================


@app.route('/login', methods=['GET', 'POST'])
def login():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits) for x in range(32))

    login_session['state'] = state

    if request.method == 'POST':
        email = request.form['emailinput']
        password = request.form['passinput']
        user = session.query(User).filter_by(email=email).first()
        try:
            if user.verify_password(password):
                login_user(user, force=True)
                flash("You have logged in successfully " + user.name)
                user.is_authenticated = True
                return redirect(url_for('showCatalog'))
            else:
                flash("You entered an incorrect password. Please try again")
                return redirect(url_for('login'))
        except:
            flash("User does not exist. Please create an account")
            return redirect(url_for('signup'))
    else:
        return render_template('login.html', STATE=state)


@app.route('/logout', methods=['GET', 'POST'])
def logout():
    if request.method == 'POST':
        flask_login.logout_user()
        flash("Logout Successful")
        return redirect(url_for('showCatalog'))
    else:
        return render_template('logout.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        user = request.form['nameinput']
        email = request.form['emailinput']
        password = request.form['passinput']
        newUser = User(name=user, email=email)
        newUser.hash_password(password)

        session.add(newUser)
        session.commit()

        login_user(newUser, force=True)
        newUser.is_authenticated=True

        flash("Welcome "+user+". You have successfully signed up")
        return redirect(url_for('showCatalog'))
    else:
        return render_template('signup.html')


@app.route('/')
@app.route('/catalog')
def showCatalog():
    latest = session.query(Item).all()[-5:]
    return render_template('catalog.html', latest=latest)


@app.route('/catalog/new', methods=['GET', 'POST'])
@flask_login.login_required
def newCategory():
    if request.method == 'POST':
        existingCats = [cat.name for cat in session.query(Category).all()]

        name = request.form['cat_name']
        user = flask_login.current_user

        if name in existingCats:

        newCat = Category(name=name, user_id=user.id)
        session.add(newCat)
        session.commit()

        flash("Created " + str(name) + " successfully")
        return redirect(url_for('showCatItems', cat_name=name))
    else:
        return render_template('newcategory.html')


@app.route('/catalog/<string:cat_name>/edit', methods=['GET', 'POST'])
@flask_login.login_required
def editCategory(cat_name):
    editedCat = session.query(Category).filter_by(name=cat_name).one()
    if user_check(editedCat):
        if request.method == 'POST':
            existingCats = [cat.name for cat in session.query(Category).all()]

            name = request.form['cat_name']

            if name != '' and name != None:
                editedCat.name = name

            session.add(editedCat)
            session.commit()

            flash("Edited " + str(name) + " successfully")
            return redirect(url_for('showCatItems', cat_name=name))
        else:
            return render_template('editcategory.html', cat_name=cat_name)
    else:
        flash("You are not the creator of this item/category")
        return redirect(url_for('showCatalog'))


@app.route('/catalog/<string:cat_name>/delete', methods=['GET', 'POST'])
@flask_login.login_required
def deleteCategory(cat_name):
    currentCat = session.query(Category).filter_by(name=cat_name).one()
    if user_check(currentCat):
        if request.method == 'POST':
            cat_items = session.query(Item).filter_by(cat_id=currentCat.id).all()
            for item in cat_items:
                session.delete(item)

            session.delete(currentCat)
            session.commit()

            flash("Category deleted")
            return redirect(url_for('showCatalog'))
        else:
            return render_template('deletecategory.html', cat_name=cat_name)
    else:
        flash("You are not the creator of this item/category")
        return redirect(url_for('showCatalog'))


@app.route('/catalog/<string:cat_name>')
@app.route('/catalog/<string:cat_name>/items')
def showCatItems(cat_name):
    currentCat = session.query(Category).filter_by(name=cat_name).one()
    items = session.query(Item).filter_by(cat_id=currentCat.id).all()
    return render_template('showitems.html', cat_name=cat_name, items=items)


@app.route('/catalog/<string:cat_name>/new', methods=['GET', 'POST'])
@flask_login.login_required
def newItem(cat_name):
    if request.method == 'POST':
        cat = session.query(Category).filter_by(name=cat_name).one()
        existingItems = [item.name for item in session.query(Item).filter_by(cat_id=cat.id]).all()]

        name = request.form['item_name']
        description = request.form['item_description']
        user = flask_login.current_user

        createdItem = Item(name=name, description=description,
                            cat_id=cat.id, user_id=user.id)
        session.add(createdItem)
        session.commit()

        flash("Created " + str(name) + " successfully")
        return redirect(url_for('showItemDescription',
                                cat_name=cat_name,
                                item_name=name))
    else:
        return render_template('newitem.html', cat_name=cat_name)


@app.route('/catalog/<string:cat_name>/<string:item_name>/edit',
            methods=['GET', 'POST'])
@flask_login.login_required
def editItem(cat_name, item_name):
    editedItem = session.query(Item).filter_by(name=item_name).one()
    if user_check(editedItem):
        if request.method == 'POST':
            cat = session.query(Category).filter_by(name=cat_name).one()
            existingItems = [item.name for item in session.query(Item).filter_by(cat_id=cat.id]).all()]

            name = request.form['item_name']
            description = request.form['item_description']

            if name != '' and name != None:
                editedItem.name = name
                item_name = name
            if description != '' and description != None:
                editedItem.description = description

            session.add(editedItem)
            session.commit()

            flash("Edited " + str(name) + " successfully")
            return redirect(url_for('showItemDescription',
                                        cat_name=cat_name,
                                        item_name=item_name))
        else:
            return render_template('edititem.html',
                                    cat_name=cat_name,
                                    item_name=item_name)
    else:
        flash("You are not the creator of this item/category")
        return redirect(url_for('showCatalog'))


@app.route('/catalog/<string:cat_name>/<string:item_name>/delete',
            methods=['GET', 'POST'])
@flask_login.login_required
def deleteItem(cat_name, item_name):
    currentItem = session.query(Item).filter_by(name=item_name).one()
    if user_check(currentItem):
        if request.method == 'POST':
            session.delete(currentItem)
            session.commit()

            flash("Deleted item successfully")
            return redirect(url_for('showCatItems', cat_name=cat_name))
        else:
            return render_template('deleteitem.html',
                                    cat_name=cat_name,
                                    item_name=item_name)
    else:
        flash("You are not the creator of this item/category")
        return redirect(url_for('showCatalog'))


@app.route('/catalog/<string:cat_name>/<string:item_name>')
def showItemDescription(cat_name, item_name):
    item = session.query(Item).filter_by(name=item_name).one_or_none()
    if item is None:
        flash("Invalid item id")
        return redirect(url_for('showCatItems', cat_name=cat_name))

    return render_template('showitemdetail.html',
                            cat_name=cat_name,
                            item=item)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
