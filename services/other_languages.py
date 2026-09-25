"""Languages a user can speak beyond the seven Wingman supports end to end.

With one of these, Wingman passes no language to speech recognition (Parakeet
and the subscription detect it themselves), tells the conversation model the
language by name, and speaks through a provider that has voices for it
(Inworld) or whatever the user brings. The list gives the client something to
search in every app language; what is not in it the support model names
(services/other_language.py).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OtherLanguage:
    code: str
    """ISO 639-1 where there is one, else 639-3."""
    native: str
    en: str
    de: str
    fr: str
    es: str


# The 25 languages Parakeet TDT 0.6B v3 transcribes, as ISO 639-1 codes
# (model card, nvidia/parakeet-tdt-0.6b-v3).
PARAKEET_LANGUAGES = frozenset(
    "bg hr cs da nl en et fi fr de el hu it lv lt mt pl pt ro sk sl es sv ru uk".split()
)

OTHER_LANGUAGES: tuple[OtherLanguage, ...] = tuple(
    OtherLanguage(*row)
    for row in (
        ("pl", "Polski", "Polish", "Polnisch", "Polonais", "Polaco"),
        ("ru", "Русский", "Russian", "Russisch", "Russe", "Ruso"),
        ("uk", "Українська", "Ukrainian", "Ukrainisch", "Ukrainien", "Ucraniano"),
        ("cs", "Čeština", "Czech", "Tschechisch", "Tchèque", "Checo"),
        ("sk", "Slovenčina", "Slovak", "Slowakisch", "Slovaque", "Eslovaco"),
        ("sl", "Slovenščina", "Slovenian", "Slowenisch", "Slovène", "Esloveno"),
        ("hr", "Hrvatski", "Croatian", "Kroatisch", "Croate", "Croata"),
        ("sr", "Српски", "Serbian", "Serbisch", "Serbe", "Serbio"),
        ("bs", "Bosanski", "Bosnian", "Bosnisch", "Bosnien", "Bosnio"),
        ("bg", "Български", "Bulgarian", "Bulgarisch", "Bulgare", "Búlgaro"),
        ("ro", "Română", "Romanian", "Rumänisch", "Roumain", "Rumano"),
        ("hu", "Magyar", "Hungarian", "Ungarisch", "Hongrois", "Húngaro"),
        ("el", "Ελληνικά", "Greek", "Griechisch", "Grec", "Griego"),
        ("tr", "Türkçe", "Turkish", "Türkisch", "Turc", "Turco"),
        ("sv", "Svenska", "Swedish", "Schwedisch", "Suédois", "Sueco"),
        ("da", "Dansk", "Danish", "Dänisch", "Danois", "Danés"),
        ("nb", "Norsk", "Norwegian", "Norwegisch", "Norvégien", "Noruego"),
        ("fi", "Suomi", "Finnish", "Finnisch", "Finnois", "Finés"),
        ("et", "Eesti", "Estonian", "Estnisch", "Estonien", "Estonio"),
        ("lv", "Latviešu", "Latvian", "Lettisch", "Letton", "Letón"),
        ("lt", "Lietuvių", "Lithuanian", "Litauisch", "Lituanien", "Lituano"),
        ("mt", "Malti", "Maltese", "Maltesisch", "Maltais", "Maltés"),
        ("ga", "Gaeilge", "Irish", "Irisch", "Irlandais", "Irlandés"),
        ("cy", "Cymraeg", "Welsh", "Walisisch", "Gallois", "Galés"),
        ("is", "Íslenska", "Icelandic", "Isländisch", "Islandais", "Islandés"),
        ("sq", "Shqip", "Albanian", "Albanisch", "Albanais", "Albanés"),
        ("mk", "Македонски", "Macedonian", "Mazedonisch", "Macédonien", "Macedonio"),
        ("ca", "Català", "Catalan", "Katalanisch", "Catalan", "Catalán"),
        ("eu", "Euskara", "Basque", "Baskisch", "Basque", "Vasco"),
        ("gl", "Galego", "Galician", "Galicisch", "Galicien", "Gallego"),
        ("lb", "Lëtzebuergesch", "Luxembourgish", "Luxemburgisch", "Luxembourgeois", "Luxemburgués"),
        ("be", "Беларуская", "Belarusian", "Belarussisch", "Biélorusse", "Bielorruso"),
        ("ka", "ქართული", "Georgian", "Georgisch", "Géorgien", "Georgiano"),
        ("hy", "Հայերեն", "Armenian", "Armenisch", "Arménien", "Armenio"),
        ("az", "Azərbaycanca", "Azerbaijani", "Aserbaidschanisch", "Azéri", "Azerí"),
        ("kk", "Қазақ тілі", "Kazakh", "Kasachisch", "Kazakh", "Kazajo"),
        ("ar", "العربية", "Arabic", "Arabisch", "Arabe", "Árabe"),
        ("he", "עברית", "Hebrew", "Hebräisch", "Hébreu", "Hebreo"),
        ("fa", "فارسی", "Persian", "Persisch", "Persan", "Persa"),
        ("hi", "हिन्दी", "Hindi", "Hindi", "Hindi", "Hindi"),
        ("ur", "اردو", "Urdu", "Urdu", "Ourdou", "Urdu"),
        ("bn", "বাংলা", "Bengali", "Bengalisch", "Bengali", "Bengalí"),
        ("ta", "தமிழ்", "Tamil", "Tamil", "Tamoul", "Tamil"),
        ("te", "తెలుగు", "Telugu", "Telugu", "Télougou", "Telugu"),
        ("zh", "中文", "Chinese", "Chinesisch", "Chinois", "Chino"),
        ("ja", "日本語", "Japanese", "Japanisch", "Japonais", "Japonés"),
        ("ko", "한국어", "Korean", "Koreanisch", "Coréen", "Coreano"),
        ("vi", "Tiếng Việt", "Vietnamese", "Vietnamesisch", "Vietnamien", "Vietnamita"),
        ("th", "ไทย", "Thai", "Thailändisch", "Thaï", "Tailandés"),
        ("id", "Bahasa Indonesia", "Indonesian", "Indonesisch", "Indonésien", "Indonesio"),
        ("ms", "Bahasa Melayu", "Malay", "Malaiisch", "Malais", "Malayo"),
        ("fil", "Filipino", "Filipino", "Filipino", "Filipino", "Filipino"),
        ("sw", "Kiswahili", "Swahili", "Suaheli", "Swahili", "Suajili"),
        ("af", "Afrikaans", "Afrikaans", "Afrikaans", "Afrikaans", "Afrikáans"),
    )
)

BY_CODE = {language.code: language for language in OTHER_LANGUAGES}

ALIASES: dict[str, tuple[str, ...]] = {
    "fa": ("Farsi",),
    "nb": ("Bokmål", "Norsk bokmål", "Nynorsk"),
    "fil": ("Tagalog",),
    "zh": ("Mandarin", "Mandarin Chinese", "Chinesisch Mandarin", "Kantonesisch", "Cantonese"),
    "ms": ("Malaysian",),
    "sr": ("Srpski",),
}
"""Other names people use, searched like the names above."""
