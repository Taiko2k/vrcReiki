import sys
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject, Gio, GLib, Gdk, Graphene, Gsk
import vrchatapi
from vrchatapi.api import authentication_api, friends_api
from vrchatapi.exceptions import UnauthorizedException
from vrchatapi.models.two_factor_auth_code import TwoFactorAuthCode
from vrchatapi.models.two_factor_email_code import TwoFactorEmailCode
from vrchatapi.api import authentication_api, friends_api
from vrchatapi.exceptions import UnauthorizedException
from vrchatapi.models.two_factor_auth_code import TwoFactorAuthCode
from vrchatapi.models.two_factor_email_code import TwoFactorEmailCode
import os
import json
from http.cookiejar import LWPCookieJar
import hashlib
import base64
import requests
import pickle
import time
import threading

AUTH_FILE = 'auth_data.pkl'
DATA_FILE = 'user_data.pkl'
USER_ICON_CACHE = "cache/avatar1"

USER_AGENT = 'taiko2k-moonbeam'
REQUEST_DL_HEADER = {
    'User-Agent': USER_AGENT,
}

if not os.path.exists(USER_ICON_CACHE):
    os.makedirs(USER_ICON_CACHE)



def filename_hasher(data):
    hash_bytes = hashlib.sha256(data.encode()).digest()
    hash_str = base64.urlsafe_b64encode(hash_bytes).decode().rstrip('=')
    return hash_str

COPY_FRIEND_PROPERTIES = [
    "location", "id", "last_platform", "display_name", "user_icon", "status", "status_description", "bio", "is_friend",
    "last_platform",
]

RUNNING = True


class FriendRow(GObject.Object):
    name = GObject.Property(type=str, default='')
    status = GObject.Property(type=int, default=0)
    mini_icon_filepath = GObject.Property(type=str, default='')

    def __init__(self):
        super().__init__()
        self.name = ""
        self.mini_icon_filepath = None
        self.status = 0
        self.is_user = False

class Friend():
    def __init__(self, **kwargs):
        for item in COPY_FRIEND_PROPERTIES:
            setattr(self, item, None)
        for key, value in kwargs.items():
            setattr(self, key, value)


class Job():
    def __init__(self, name: str, data=None):
        self.name = name
        self.data = data

test = Job("a", "b")

class VRCZ:

    def __init__(self):
        self.logged_in = False

        self.current_user_name = ""  # in-game name
        self.friend_id_list = []
        self.friend_objects = {}
        self.user_object = None

        self.error_log = []  # in event of any error, append human-readable string explaining error
        self.api_client = vrchatapi.ApiClient()
        self.auth_api = authentication_api.AuthenticationApi(self.api_client)
        self.cookie_file_path = 'cookie_data'

        self.jobs = []
        self.posts = []

    def save_cookies(self):
        cookie_jar = LWPCookieJar(filename=self.cookie_file_path)
        for cookie in self.api_client.rest_client.cookie_jar:
            cookie_jar.set_cookie(cookie)
        cookie_jar.save()

    def load_cookies(self):
        cookie_jar = LWPCookieJar(self.cookie_file_path)
        try:
            cookie_jar.load()
        except FileNotFoundError:
            cookie_jar.save()
            return
        for cookie in cookie_jar:
            self.api_client.rest_client.cookie_jar.set_cookie(cookie)
    def load_app_data(self):  # Run on application start
        self.load_cookies()
        if os.path.isfile(DATA_FILE):
            with open(DATA_FILE, 'rb') as file:
                d = pickle.load(file)
                print(d)
                if "friends" in d:
                    for k, v in d["friends"].items():
                        friend = Friend(**v)
                        self.friend_objects[k] = friend
                if "self" in d:
                    self.user_object = Friend(**d["self"])


    def save_app_data(self):
        self.save_cookies()
        d = {}
        friends = {}
        for k, v in self.friend_objects.items():
            friends[k] = v.__dict__

        d["friends"] = friends
        d["self"] = self.user_object.__dict__
        with open(DATA_FILE, 'wb') as file:
            pickle.dump(d, file)


    def sign_in_step1(self, username, password):
        self.api_client.configuration.username = username
        self.api_client.configuration.password = password

        try:
            user = self.auth_api.get_current_user()
            self.logged_in = True
            self.current_user_name = user.display_name
        except UnauthorizedException as e:
            if "2 Factor Authentication" in e.reason:
                print("2FA required. Please provide the code sent to your email.")
                return
            else:
                print(f"Error during authentication: {e}")
                self.error_log.append(f"Error during authentication: {e}")
                raise

    def sign_in_step2(self, email_code):
        try:
            self.auth_api.verify2_fa_email_code(two_factor_email_code=TwoFactorEmailCode(email_code))
            self.logged_in = True
            # Save authentication data for future use

        except Exception as e:
            self.error_log.append(f"Error during 2FA verification: {e}")
            raise ValueError(f"Error during 2FA verification: {e}")

    def update(self):

        # Try authenticate
        try:
            user = self.auth_api.get_current_user()
            self.logged_in = True
        except:
            print("ERROR --1")
            self.logout()
            return 1

        self.current_user_name = user.display_name
        self.friend_id_list = user.friends
        print(user)

        # Update user data
        if self.user_object is None:
            self.user_object = Friend()
        for key in COPY_FRIEND_PROPERTIES:
            try:
                setattr(self.user_object, key, getattr(user, key))
            except:
                print("no user key ", key)

        job = Job("download-check-user-icon", self.user_object)
        self.jobs.append(job)

        # Fetch the list of friends
        friends_api_instance = friends_api.FriendsApi(self.api_client)
        friends_list = friends_api_instance.get_friends()
        friends_list.extend(friends_api_instance.get_friends(offline="true"))

        # Update local friend data
        for r in friends_list:
            print(r)
            t = self.friend_objects.get(r.id)
            if not t:
                print("NEW FRIEND OBJECT")
                t = Friend()
            else:
                print("UPDATE FRIEND OBJECT")
                if t.display_name != r.display_name:
                    print("Friend changed their name!")
                    print(t)
                    print(r)
            for key in COPY_FRIEND_PROPERTIES:
                setattr(t, key, getattr(r, key))

            self.friend_objects[r.id] = t


        # Check user icon is cached
        for k, v in self.friend_objects.items():
            key = filename_hasher(v.user_icon)
            key_path = os.path.join(USER_ICON_CACHE, key)
            if v.user_icon and not os.path.isfile(key_path):
                print("queue download user icon")
                job = Job("download-check-user-icon", v)
                self.jobs.append(job)

        self.save_app_data()
        print(f"Logged in as: {self.current_user_name}")
        return 0

    def logout(self):
        print("Logout")

        if os.path.exists(self.AUTH_FILE):
            os.remove(self.AUTH_FILE)

        self.__init__()

    def worker(self):
        while RUNNING:
            if self.jobs:
                job = self.jobs.pop(0)
                print("doing job")
                print(job.name)

                if job.name == "download-check-user-icon":

                    v = job.data
                    if v.user_icon and v.user_icon.startswith("http"):
                        print("check for icon")
                        key = filename_hasher(v.user_icon)
                        key_path = os.path.join(USER_ICON_CACHE, key)
                        if key not in os.listdir(USER_ICON_CACHE):
                            print("download icon")

                            response = requests.get(v.user_icon, headers=REQUEST_DL_HEADER)
                            with open(key_path, 'wb') as f:
                                f.write(response.content)

                            job = Job("update-friend-list")
                            self.posts.append(job)
                            # v.mini_icon_filepath = key_path

            time.sleep(2)





vrcz = VRCZ()
vrcz.load_app_data()

thread = threading.Thread(target=vrcz.worker)
thread.daemon = True  # Set the thread as a daemon
thread.start()


class UserIconDisplay(Gtk.Widget):
    icon_path = GObject.Property(type=str, default='')
    status_mode = GObject.Property(type=int, default=0)
    def __init__(self):
        super().__init__()
        self.connect("notify::icon-path", self._on_icon_path_changed)
        self.connect("notify::status-mode", self._on_status_mode_changed)

        self.icon_texture = None

        self.rect = Graphene.Rect()
        self.point = Graphene.Point()
        self.colour = Gdk.RGBA()
        self.r_rect = Gsk.RoundedRect()

    def _on_status_mode_changed(self, widget, param):
        self.queue_draw()
    def _on_icon_path_changed(self, widget, param):
        #print(f"Icon path changed to: {self.icon_path}")
        if self.icon_path:
            if not os.path.isfile(self.icon_path):  # warning todo
                return
            self.icon_texture = Gdk.Texture.new_from_filename(self.icon_path)
            self.queue_draw()

    def set_color(self, r, g, b, a=1.0):
        self.colour.red = r
        self.colour.green = g
        self.colour.blue = b
        self.colour.alpha = a

    def set_rect(self, x, y, w, h):
        self.rect.init(x, y, w, h)

    def set_r_rect(self, x, y, w, h, c=0):
        self.set_rect(x, y, w, h)
        self.r_rect.init_from_rect(self.rect, c)

    def do_snapshot(self, s):
        w = self.get_width()
        h = self.get_height()
        x = 0
        y = 0

        if self.icon_texture:

            self.set_r_rect(x, y, w, h, 360)


            s.push_rounded_clip(self.r_rect)
            s.append_texture(self.icon_texture, self.rect)
            s.pop()

        q = w * 0.37
        xx = w * 0.68
        yy = xx

        self.set_r_rect(xx, yy, q, q, 360)

        s.push_rounded_clip(self.r_rect)
        if self.status_mode == 0:
            self.set_color(0.2, 0.2, 0.2, 1)
        if self.status_mode == 1:
            self.set_color(0.7, 0.7, 0.7, 1)
        if self.status_mode == 2:
            self.set_color(0.35, 0.85, 0.3, 1)
        if self.status_mode == 3:
            self.set_color(0.8, 0.2, 0.2, 1)
        if self.status_mode == 4:
            self.set_color(0.3, 0.75, 1, 1)
        if self.status_mode == 5:
            self.set_color(0.8, 0.6, 0.2, 1)

        s.append_color(self.colour, self.rect)
        s.pop()

        self.set_color(0.1, 0.1, 0.1, 1)
        s.append_border(self.r_rect, [1] * 4, [self.colour] * 4)


        #s.append_color(self.colour, self.rect)



class MainWindow(Adw.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.outer_box = Gtk.Box()

        self.set_default_size(1000, 500)
        self.set_title("Moonbeam")

        self.nav = Adw.NavigationSplitView()
        self.set_content(self.nav)
        self.header = Adw.HeaderBar()
        self.n1 = Adw.NavigationPage()
        self.n0 = Adw.NavigationPage()
        self.t1 = Adw.ToolbarView()
        self.t1.add_top_bar(self.header)
        self.n1.set_child(self.t1)
        self.nav.set_content(self.n1)
        self.nav.set_sidebar(self.n0)

        self.vsw1 = Adw.ViewSwitcher()
        self.vst1 = Adw.ViewStack()
        self.vsw1.set_stack(self.vst1)

        self.header.set_title_widget(self.vsw1)
        self.t1.set_content(self.vst1)


        # ---- Info page
        self.info_list = Gtk.ListBox()
        self.info_list.set_selection_mode(Gtk.SelectionMode.NONE)
        style_context = self.info_list.get_style_context()
        style_context.add_class('boxed-ist')

        self.c1 = Adw.Clamp()

        self.info_box1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self.info_box_header = Gtk.Box()
        self.info_box1.append(self.info_box_header)

        self.info_box_header_title = Gtk.Label(label="Display Name")
        self.info_box_header_title.set_selectable(True)
        self.set_style(self.info_box_header_title, "title-2")
        self.info_box_header.set_margin_top(6)
        self.info_box_header.append(self.info_box_header_title)

        #self.c1.set_child(self.info_list)
        self.c1.set_child(self.info_box1)

        self.vst1.add_titled_with_icon(self.c1, "info", "Player Info", "user-info-symbolic")

        self.info_name = Adw.ActionRow()
        self.info_name.set_subtitle("Test")
        self.info_name.set_title("Test3")
        self.set_style(self.info_name, "property")
        self.info_list.append(self.info_name)

        # ------


        style_context = self.get_style_context()
        style_context.add_class('devel')



        #self.set_titlebar()


        # Friend list box
        self.friend_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.friend_list_box.set_size_request(220, -1)
        #self.outer_box.append(self.friend_list_box)

        self.n0.set_child(self.friend_list_box)

        self.friend_data = {}
        self.friend_list_view = Gtk.ListView()
        self.friend_list_scroll = Gtk.ScrolledWindow()
        self.friend_list_scroll.set_vexpand(True)
        self.friend_list_scroll.set_child(self.friend_list_view)
        self.friend_list_box.append(self.friend_list_scroll)
        self.friend_ls = Gio.ListStore(item_type=FriendRow)

        ss = Gtk.SingleSelection()
        ss.set_model(self.friend_ls)
        self.friend_list_view.set_model(ss)

        factory = Gtk.SignalListItemFactory()

        def f_setup(fact, item):

            holder = Gtk.Box()
            holder.set_margin_top(2)
            holder.set_margin_bottom(2)
            holder.set_margin_start(4)

            icon = UserIconDisplay()
            icon.set_size_request(43, 43)
            holder.append(icon)

            # image = Gtk.Image()
            # image.set_size_request(40, 40)
            # holder.append(image)

            label = Gtk.Label(halign=Gtk.Align.START)
            label.set_selectable(False)
            label.set_margin_start(9)
            label.set_use_markup(True)

            holder.append(label)

            item.set_child(holder)
            item.label = label
            # item.image = image
            item.icon = icon

        factory.connect("setup", f_setup)

        def f_bind(fact, row):
            friend = row.get_item()
            #row.label.set_label(friend.name)

            friend.bind_property("name",
                          row.label, "label",
                          GObject.BindingFlags.SYNC_CREATE)

            # friend.bind_property("mini_icon_filepath",
            #               row.image, "file",
            #               GObject.BindingFlags.SYNC_CREATE)

            friend.bind_property("mini_icon_filepath",
                          row.icon, "icon_path",
                          GObject.BindingFlags.SYNC_CREATE)

            friend.bind_property("status",
                          row.icon, "status_mode",
                          GObject.BindingFlags.SYNC_CREATE)

        factory.connect("bind", f_bind)

        self.friend_list_view.set_factory(factory)

        # ---------------

        self.event_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.c4 = Adw.Clamp()
        self.c4.set_child(self.event_box)
        self.vst1.add_titled_with_icon(self.c4, "event", "Monitor", "radio-checked-symbolic")

        # ----------------
        self.outer_box.append(Gtk.Separator())

        self.dev_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.c2 = Adw.Clamp()
        self.c2.set_child(self.dev_box)
        self.vst1.add_titled_with_icon(self.c2, "dev", "Dev Menu", "pan-down-symbolic")
        self.dev_label = Gtk.Label(label="Dev Menu")
        #self.notebook.append_page(self.dev_box, self.dev_label)

        self.test_button = Gtk.Button(label="Connect and Update")
        self.test_button.connect("clicked", self.test3)
        self.dev_box.append(self.test_button)

        self.test_button = Gtk.Button(label="Load Friend List")
        self.test_button.connect("clicked", self.test2)
        self.dev_box.append(self.test_button)

        # self.gps_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # self.gps_label = Gtk.Label(label="GPS")
        # self.notebook.append_page(self.gps_box, self.gps_label)
        #
        # self.user_info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # self.user_info_label = Gtk.Label(label="User Info")
        # self.notebook.append_page(self.user_info_box, self.user_info_label)

        #self.outer_box.append(Gtk.Separator())

        # Login box
        self.login_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self.c3 = Adw.Clamp()
        self.c3.set_child(self.login_box)
        self.vst1.add_titled_with_icon(self.c3, "login", "Login", "dialog-password-symbolic")

        #self.login_box.set_size_request(200, -1)
        self.login_box.set_spacing(6)
        self.login_box.set_margin_top(12)
        self.login_box.set_margin_bottom(12)
        self.login_box.set_margin_start(12)
        self.login_box.set_margin_end(12)
        #self.outer_box.append(self.login_box)

        self.username_entry = Gtk.Entry(placeholder_text="Username")
        self.password_entry = Gtk.Entry(placeholder_text="Password", visibility=False)
        self.login_box.append(self.username_entry)
        self.login_box.append(self.password_entry)

        self.request_code_button = Gtk.Button(label="Request Code")
        self.request_code_button.set_margin_bottom(30)
        self.request_code_button.connect("clicked", self.activate_get_code)
        self.login_box.append(self.request_code_button)

        self.two_fa_entry = Gtk.Entry(placeholder_text="2FA Code")
        self.login_box.append(self.two_fa_entry)

        self.login_button = Gtk.Button(label="Verify Code")
        self.login_button.connect("clicked", self.activate_verify_code)
        self.login_box.append(self.login_button)
        self.login_button.set_margin_bottom(60)

        self.logout_button = Gtk.Button(label="Logout")
        self.logout_button.connect("clicked", self.activate_logout)
        self.logout_button.set_margin_bottom(20)
        self.login_box.append(self.logout_button)

        # self.test_button = Gtk.Button(label="_test")
        # self.test_button.connect("clicked", self.activate_test)
        # self.login_box.append(self.test_button)

        #self.login_box.set_visible(False)

        GLib.timeout_add(900, self.heartbeat)

    def set_style(self, target, name):
        style_context = target.get_style_context()
        style_context.add_class(name)
    def set_friend_row_data(self, id):

        row = self.friend_data.get(id)
        friend = vrcz.friend_objects.get(id)
        if friend is None and id == vrcz.user_object.id:
            friend = vrcz.user_object
        if row and friend:
            row.name = f"<b>{friend.display_name}</b>"

            if friend.status == "offline":
                row.status = 0
            elif friend.status != "offline" and friend.location == "offline":
                row.status = 1
            elif friend.status == "active" and friend.location != "offline":
                row.status = 2
            elif friend.status == "busy" and friend.location != "offline":
                row.status = 3
            elif friend.status == "join me" and friend.location != "offline":
                row.status = 4
            elif friend.status == "ask me" and friend.location != "offline":
                row.status = 5

            if friend.user_icon:
                key = filename_hasher(friend.user_icon)
                key_path = os.path.join(USER_ICON_CACHE, key)
                row.mini_icon_filepath = key_path


    def heartbeat(self):
        if vrcz.posts:
            post = vrcz.posts.pop(0)
            print("post")
            print(post.name)
            if post.name == "update-friend-list":
                print(0)
                for k, v in self.friend_data.items():
                    print(00)
                    self.set_friend_row_data(k)

        GLib.timeout_add(250, self.heartbeat)

    def test2(self, button):
        self.update_friend_list()
    def test3(self, button):
        if vrcz.update():
            self.login_box.set_visible(True)
    def update_friend_list(self):
        self.friend_ls.remove_all()
        #print(vrcz.friend_objects)
        if vrcz.user_object:
            fd = FriendRow()
            fd.is_user = True
            self.friend_data[vrcz.user_object.id] = fd
            self.set_friend_row_data(vrcz.user_object.id)
            self.friend_ls.append(fd)

        for k, v in vrcz.friend_objects.items():
            if k not in self.friend_data:
                fd = FriendRow()

                self.friend_data[k] = fd
                self.set_friend_row_data(k)
                self.friend_ls.append(fd)

        def get_weight(row):
            if row.is_user:
                return -1
            if row.status == 4:
                return 0
            if row.status == 2:
                return 1
            if row.status == 5:
                return 2
            if row.status == 3:
                return 3
            if row.status == 1:
                return 4
            return 5


        def compare(a, b):

            aw = get_weight(a)
            bw = get_weight(b)
            if aw == bw:
                return 0
            if aw < bw:
                return -1
            return 1

        self.friend_ls.sort(compare)


    def activate_test(self, button):
        vrcz.update()

    def activate_get_code(self, button):
        username = self.username_entry.get_text()
        password = self.password_entry.get_text()
        try:
            vrcz.sign_in_step1(username, password)
        except ValueError as e:
            print(e)

    def activate_verify_code(self, button):
        code = self.two_fa_entry.get_text()
        try:
            vrcz.sign_in_step2(code)
            if vrcz.update():
                self.login_box.set_visible(False)
        except ValueError as e:
            print(e)

    def activate_logout(self, button):
        vrcz.logout()
        # Here you can also reset the UI fields if needed


class VRCZAPP(Adw.Application):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.connect('activate', self.on_activate)

    def on_activate(self, app):
        self.win = MainWindow(application=app)
        self.win.present()


app = VRCZAPP(application_id="com.github.taiko2k.vrcz")
app.run(sys.argv)
RUNNING = False
time.sleep(2)