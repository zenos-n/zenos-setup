import re
from gi.repository import Adw, Gtk

# replace this with your actual import once zenpkgs/core is wired up
all_languages = {"en_US": "English (US)", "pl_PL": "Polski"}
current_language = "en_US"

class LanguageRow(Adw.ActionRow):
    def __init__(self, title, subtitle, selected_lang_dict, **kwargs):
        super().__init__(**kwargs)
        self.set_title(title)
        self.set_subtitle(subtitle)
        self.__title = title
        self.__subtitle = subtitle
        self.__selected_language = selected_lang_dict

        # doing this in python avoids needing a separate widget-language.ui file
        self.select_button = Gtk.CheckButton()
        self.select_button.set_valign(Gtk.Align.CENTER)
        self.add_prefix(self.select_button)

        self.select_button.connect("toggled", self.__on_toggled)
        self.set_activatable_widget(self.select_button)

    def __on_toggled(self, widget):
        if widget.get_active():
            self.__selected_language["title"] = self.__title
            self.__selected_language["code"] = self.__subtitle
            # emit a generic signal or call a method so the parent knows to update
            self.get_parent().emit("row-activated", self)


@Gtk.Template(resource_path="/com/negzero/zenos/setup/views/language/layout.ui")
class Page(Adw.Bin):
    __gtype_name__ = "ZenOSDefaultLanguage"

    entry_search_language = Gtk.Template.Child()
    all_languages_group = Gtk.Template.Child()

    def __init__(self, router, **kwargs):
        super().__init__(**kwargs)
        self.router = router
        self.selected_language = {"title": None, "code": None}
        self.__language_rows = []

        self.search_controller = Gtk.EventControllerKey.new()
        self.search_controller.connect("key-released", self.__on_search)
        self.entry_search_language.add_controller(self.search_controller)

        # signals
        self.all_languages_group.connect("row-activated", self.__verify)

        # lock the router's next button initially so they can't skip
        self.router.btn_next.set_sensitive(False)

        self.__generate_rows()

    def __verify(self, *args):
        # ungrey the global next button if a valid lang is picked
        has_lang = self.selected_language["code"] is not None
        self.router.btn_next.set_sensitive(has_lang)

    def __generate_rows(self):
        group = None
        for code, title in all_languages.items():
            row = LanguageRow(title, code, self.selected_language)

            # link the radio buttons together
            if group:
                row.select_button.set_group(group)
            else:
                group = row.select_button

            self.__language_rows.append(row)
            self.all_languages_group.append(row)

            if current_language == code:
                row.select_button.set_active(True)

    def __on_search(self, *args):
        query = re.sub(r"[^a-zA-Z0-9 ]", "", self.entry_search_language.get_text().lower())
        for row in self.__language_rows:
            title = re.sub(r"[^a-zA-Z0-9 ]", "", row.get_title().lower())
            sub = re.sub(r"[^a-zA-Z0-9 ]", "", row.get_subtitle().lower())
            match = re.search(query, f"{title} {sub}", re.IGNORECASE)
            row.set_visible(match is not None)
