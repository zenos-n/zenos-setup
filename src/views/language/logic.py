from gi.repository import Adw, Gtk
from babel import Locale
import re

all_locale = [
    "ab_GE.UTF-8", "aa_DJ.UTF-8", "af_ZA.UTF-8", "ak_GH.UTF-8", "sq_AL.UTF-8",
    "am_ET.UTF-8", "ar_EG.UTF-8", "an_ES.UTF-8", "hy_AM.UTF-8", "as_IN.UTF-8",
    "ar_AE.UTF-8", "az_AZ.UTF-8", "bs_BA.UTF-8", "eu_ES.UTF-8", "be_BY.UTF-8",
    "bn_BD.UTF-8", "ar_BH.UTF-8", "bi_VU.UTF-8", "br_FR.UTF-8", "bg_BG.UTF-8",
    "my_MM.UTF-8", "ca_ES.UTF-8", "de_CH.UTF-8", "ce_RU.UTF-8", "zh_CN.UTF-8",
    "cv_RU.UTF-8", "kw_GB.UTF-8", "es_CO.UTF-8", "es_CR.UTF-8", "hr_HR.UTF-8",
    "cs_CZ.UTF-8", "da_DK.UTF-8", "dv_MV.UTF-8", "nl_NL.UTF-8", "dz_BT.UTF-8",
    "en_US.UTF-8", "en_GB.UTF-8", "eo.UTF-8", "et_EE.UTF-8", "fo_FO.UTF-8",
    "hif_FJ.UTF-8", "fi_FI.UTF-8", "fr_FR.UTF-8", "ff_SN.UTF-8", "gl_ES.UTF-8",
    "ka_GE.UTF-8", "de_DE.UTF-8", "el_GR.UTF-8", "gu_IN.UTF-8", "ht_HT.UTF-8",
    "ha_NG.UTF-8", "he_IL.UTF-8", "hi_IN.UTF-8", "hu_HU.UTF-8", "ia_FR.UTF-8",
    "id_ID.UTF-8", "en_IE.UTF-8", "ga_IE.UTF-8", "ig_NG.UTF-8", "ik_CA.UTF-8",
    "is_IS.UTF-8", "it_IT.UTF-8", "iu_CA.UTF-8", "ja_JP.UTF-8", "kl_GL.UTF-8",
    "kn_IN.UTF-8", "ko_KR.UTF-8", "ks_IN.UTF-8@devanagari", "kk_KZ.UTF-8",
    "km_KH.UTF-8", "rw_RW.UTF-8", "ky_KG.UTF-8", "ku_TR.UTF-8", "lo_LA.UTF-8",
    "lb_LU.UTF-8", "lg_UG.UTF-8", "li_NL.UTF-8", "ln_CD.UTF-8", "lt_LT.UTF-8",
    "fr_LU.UTF-8", "lv_LV.UTF-8", "gv_GB.UTF-8", "mk_MK.UTF-8", "mg_MG.UTF-8",
    "ms_MY.UTF-8", "ml_IN.UTF-8", "mt_MT.UTF-8", "mi_NZ.UTF-8", "mr_IN.UTF-8",
    "mn_MN.UTF-8", "ne_NP.UTF-8", "en_NG.UTF-8", "nb_NO.UTF-8", "nn_NO.UTF-8",
    "no_NO.UTF-8", "nr_ZA.UTF-8", "oc_FR.UTF-8", "es_CU.UTF-8", "om_ET.UTF-8",
    "or_IN.UTF-8", "os_RU.UTF-8", "pa_IN.UTF-8", "fa_IR.UTF-8", "pl_PL.UTF-8",
    "ps_AF.UTF-8", "pt_BR.UTF-8", "ro_RO.UTF-8", "ru_RU.UTF-8", "sa_IN.UTF-8",
    "sc_IT.UTF-8", "sd_IN.UTF-8", "se_NO.UTF-8", "sm_WS.UTF-8", "en_SG.UTF-8",
    "sr_RS.UTF-8", "gd_GB.UTF-8", "wo_SN.UTF-8", "si_LK.UTF-8", "sk_SK.UTF-8",
    "sl_SI.UTF-8", "so_SO.UTF-8", "st_ZA.UTF-8", "es_ES.UTF-8", "sw_KE.UTF-8",
    "ss_ZA.UTF-8", "sv_SE.UTF-8", "ta_IN.UTF-8", "te_IN.UTF-8", "tg_TJ.UTF-8",
    "th_TH.UTF-8", "ti_ER.UTF-8", "bo_CN.UTF-8", "tk_TM.UTF-8", "tl_PH.UTF-8",
    "tn_ZA.UTF-8", "to_TO.UTF-8", "tr_TR.UTF-8", "ts_ZA.UTF-8", "tt_RU.UTF-8",
    "zh_TW.UTF-8", "ug_CN.UTF-8", "uk_UA.UTF-8", "ur_PK.UTF-8", "uz_UZ.UTF-8@cyrillic",
    "ve_ZA.UTF-8", "vi_VN.UTF-8", "wa_BE.UTF-8", "cy_GB.UTF-8", "fy_NL.UTF-8",
    "xh_ZA.UTF-8", "yi_US.UTF-8", "yo_NG.UTF-8", "zu_ZA.UTF-8", "pt_PT.UTF-8",
]

all_languages = {}

for _locale in all_locale:
    # babel hates the .UTF-8 suffix, strip it
    clean_code = _locale.split('.')[0]

    try:
        parsed_locale = Locale.parse(clean_code)
        # get name in its own language (e.g. "polski")
        native_name = parsed_locale.get_display_name(clean_code)
        # get name in english (e.g. "Polish")
        english_name = parsed_locale.get_display_name('en_US')
    except Exception:
        # fallback if babel somehow doesn't know it
        native_name = _locale
        english_name = _locale

    title = native_name if native_name else _locale
    # titlecase it so "polski" -> "Polski" for the UI, looks cleaner
    if isinstance(title, str):
        title = title.capitalize()

    search_blob = re.sub(r"[^a-zA-Z0-9 ]", "", f"{native_name or ''} {english_name or ''} {_locale}").lower()

    all_languages[_locale] = {
        "title": title,
        "search_blob": search_blob
    }

# sort alphabetically
all_languages = dict(sorted(all_languages.items(), key=lambda item: item[1]["title"]))

try:
    current_language = "{}.{}".format(
        locale.getdefaultlocale()[0], locale.getdefaultlocale()[1]
    )
except Exception:
    current_language = "en_US.UTF-8" # safe fallback if getdefaultlocale shits the bed

class LanguageRow(Adw.ActionRow):
    def __init__(self, title, subtitle, search_blob, selected_lang_dict, **kwargs):
        super().__init__(**kwargs)
        self.set_title(title)
        self.set_subtitle(subtitle)
        self.__title = title
        self.__subtitle = subtitle
        self.search_blob = search_blob # stash this here for the search controller
        self.__selected_language = selected_lang_dict

        self.select_button = Gtk.CheckButton()
        self.select_button.set_valign(Gtk.Align.CENTER)
        self.add_prefix(self.select_button)

        self.select_button.connect("toggled", self.__on_toggled)
        self.set_activatable_widget(self.select_button)

    def __on_toggled(self, widget):
        if widget.get_active():
            self.__selected_language["title"] = self.__title
            self.__selected_language["code"] = self.__subtitle
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
        for code, data in all_languages.items():
            # pass the search blob down
            row = LanguageRow(data["title"], code, data["search_blob"], self.selected_language)

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
            # just check if the query is in the pre-compiled blob
            match = re.search(query, row.search_blob, re.IGNORECASE)
            row.set_visible(match is not None)

    def get_finals(self):
        return {
            "locale": self.selected_language.get("code") or "en_US.UTF-8",
            "display_name": self.selected_language.get("title") or "English",
        }
