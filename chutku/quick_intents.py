"""Tier-0/1 router for common everyday requests (English and Romanized Hinglish).

Deterministic matching is faster and more reliable than the language model for
"open Spotify", "search YouTube for X" or "next song". A match yields an
ordinary proposal that still goes through validation, policy and verification.
Anything ambiguous returns None so the language model plans instead.
"""
from __future__ import annotations

from pathlib import Path
import re
import time

from chutku.intents.lexicon import POLITE as _POLITE, TAIL as _TAIL   # one Hinglish vocabulary for every parser
_OPEN_VERB = r"(?:open|launch|start|run|fire up|bring up)"
_HINDI_OPEN = (r"(?:kholo|khol do|khol|open karo|open kar do|open kar|chalu karo|chalu kar do|chalu kar|start karo|"
               r"start kar do|start kar|chalao|launch karo)")
_APP_WORDS = r"(?:\s+(?:app|application|program|software))?"
_SITES = {"youtube": "youtube", "yt": "youtube", "google": "google", "bing": "bing", "duckduckgo": "duckduckgo",
          "wikipedia": "wikipedia", "wiki": "wikipedia", "maps": "maps", "google maps": "maps", "github": "github",
          "amazon": "amazon", "flipkart": "flipkart"}
_SITE = r"(?P<site>youtube|yt|google maps|google|bing|duckduckgo|wikipedia|wiki|maps|github|amazon|flipkart)"
from chutku.intents.lexicon import DOMAIN as _DOMAIN
_NIGHT, _SHIFT, _REPORT = r"(?:night|naait|nait)", r"(?:shift|shipht|shipt)", r"(?:report|riport|ripot)"

_UNIT = r"(?P<unit>minutes?|mins?|min|hours?|hrs?|hr|ghante?|minute)"
_CLOSE = r"(?:close|quit|exit|band karo|band kar do|band|bund karo)"
_SLUG_STOP = {"a", "an", "the", "me", "my", "simple", "small", "basic", "nice", "new", "which", "that", "with", "for", "in", "using", "ek", "mere", "liye", "please"}
_BUILDABLE = r"(?:app|apps|application|program|software|website|web ?site|web ?app|web ?page|landing page|game|calculator|dashboard|clone|to-?do list|portfolio)"
_IN_APP = re.compile(r"\b(?:in|on|inside)\s+(?:my\s+|the\s+)?(?:whats\s?app|telegram|spotify|discord|instagram|"
                     r"brave|chrome|edge|firefox|outlook|teams|slack|vs ?code|file explorer|explorer)\b", re.I)
_ORDERING = re.compile(r"\b(?:newest|latest|oldest|biggest|largest|smallest|recent|last)\b", re.I)
PATTERNS = [
    ("build", re.compile(rf"^{_POLITE}(?:can you |could you |i want you to |i want to )?(?:build|make|create|code|develop|write|generate)\s+(?:me\s+|us\s+)?(?:a\s+|an\s+|the\s+|my\s+)?(?P<what>(?:(?!\b(?:folder|file|note|document|reminder|timer|playlist)s?\b).)*?\b{_BUILDABLE}\b.*?){_TAIL}", re.I)),
    ("build", re.compile(rf"^{_POLITE}(?:(?:mere liye|mujhe|ek)\s+)*(?P<what>.*?\b{_BUILDABLE}\b.*?)\s+(?:banao|bana do|banado|bana ke do|bana kar do|build karo|build kar do|code karo|code kar do|develop karo){_TAIL}", re.I)),
    ("close", re.compile(rf"^{_POLITE}{_CLOSE}\s+(?:the\s+|my\s+)?(?P<name>.+?){_APP_WORDS}(?:\s+window)?{_TAIL}", re.I)),
    ("close", re.compile(rf"^{_POLITE}(?P<name>.+?){_APP_WORDS}\s+{_CLOSE}{_TAIL}", re.I)),
    ("volume", re.compile(rf"^{_POLITE}(?:(?:turn|put|make)\s+(?:the\s+)?(?:volume|sound)\s+(?P<dir1>up|down)|(?:turn\s+)?(?P<dir2>up|down)\s+the\s+(?:volume|sound)|(?:volume|sound|awaaz|aawaz|awaz)\s+(?P<dir3>up|down|badhao|kam karo|kam|zyada karo|tez karo|dheere karo))(?:\s+(?:a (?:little|bit)|thoda|by (?P<step>\d{{1,2}})(?: percent|%)?))?{_TAIL}", re.I)),
    ("volume_set", re.compile(rf"^{_POLITE}(?:set\s+)?(?:the\s+)?(?:volume|sound|awaaz)\s+(?:to\s+)?(?P<level>\d{{1,3}})(?:\s*(?:%|percent))?(?:\s+(?:karo|kar do))?{_TAIL}", re.I)),
    ("mute", re.compile(rf"^{_POLITE}(?P<what>mute|unmute)(?:\s+(?:the\s+)?(?:volume|sound|pc|computer|laptop))?{_TAIL}", re.I)),
    ("brightness", re.compile(rf"^{_POLITE}(?:(?:turn|make)\s+(?:the\s+)?(?:screen\s+)?brightness\s+(?P<dir1>up|down)|(?:screen\s+)?brightness\s+(?P<dir2>up|down|badhao|kam karo|kam|zyada karo)|(?:increase|raise)\s+(?:the\s+)?brightness(?P<up>)|(?:decrease|lower|reduce)\s+(?:the\s+)?brightness(?P<down>))(?:\s+(?:a (?:little|bit)|thoda))?{_TAIL}", re.I)),
    ("brightness_set", re.compile(rf"^{_POLITE}(?:set\s+)?(?:the\s+)?(?:screen\s+)?brightness\s+(?:to\s+)?(?P<level>\d{{1,3}})(?:\s*(?:%|percent))?{_TAIL}", re.I)),
    ("remind_in", re.compile(rf"^{_POLITE}remind me (?:in|after) (?P<n>\d{{1,4}}) {_UNIT} (?:to |that |about )?(?P<message>.+?){_TAIL}", re.I)),
    ("remind_in", re.compile(rf"^{_POLITE}(?P<n>\d{{1,4}}) {_UNIT} (?:baad|me|mein) (?P<message>.+?) (?:yaad dilana|yaad dila dena|remind karna){_TAIL}", re.I)),
    ("timer", re.compile(rf"^{_POLITE}(?:set (?:a )?)?timer (?:for )?(?P<n>\d{{1,4}}) {_UNIT}{_TAIL}", re.I)),
    ("remind_at", re.compile(rf"^{_POLITE}remind me (?P<day>tomorrow )?at (?P<h>\d{{1,2}})(?::(?P<m>\d{{2}}))? ?(?P<ampm>am|pm)? (?P<day2>tomorrow )?(?:to |that |about )?(?P<message>.+?){_TAIL}", re.I)),
    ("briefing", re.compile(rf"^{_POLITE}(?:good morning|morning briefing|briefing|daily briefing|brief me|what'?s my day like|subah ki report){_TAIL}", re.I)),
    ("play", re.compile(rf"^{_POLITE}(?:play|chalao|bajao|lagao)\s+(?P<query>.+?)\s+(?:on|in)\s+(?:youtube|yt){_TAIL}", re.I)),
    ("play", re.compile(rf"^{_POLITE}(?:youtube|yt)\s+(?:pe|par|mein|me)\s+(?P<query>.+?)\s+(?:chalao|bajao|lagao|play karo|play){_TAIL}", re.I)),
    ("weather", re.compile(rf"^{_POLITE}(?:(?:what(?:'?s| is) the |how(?:'s| is) the |tell me the |check the )?weather|mausam|temperature)(?:\s+(?:like\s+)?(?:in|at|of|for)\s+(?P<city>[a-z .'-]{{2,60}}?))?(?:\s+(?:today|now|right now|currently|at the moment|tomorrow|kaisa hai|kya hai|batao|kaisa rahega))*{_TAIL}", re.I)),
    ("weather", re.compile(rf"^{_POLITE}(?P<city>[a-z .'-]{{2,60}}?)\s+(?:ka|mein|me)\s+(?:mausam|weather|temperature)(?:\s+(?:kaisa hai|kya hai|batao|kaisa rahega))?{_TAIL}", re.I)),
    ("news", re.compile(rf"^{_POLITE}(?:(?:give|tell|show|get) me |what(?:'?s| is) |any )?(?:the )?(?:(?:latest|today'?s|top|recent)\s+)?(?:news|headlines|khabar|samachar)(?:\s+(?:about|on|of|for|regarding)\s+(?P<topic>.{{2,100}}?))?(?:\s+(?:batao|sunao|dikhao))?{_TAIL}", re.I)),
    ("info_learned", re.compile(rf"^{_POLITE}(?:tumne kya (?:kya )?seekha(?: hai)?|kya seekha(?: hai)?|what (?:did|have) you "
                                rf"learn(?:ed|t)?|what skills (?:did|have) you learn(?:ed|t)?|show (?:your |the )?learned "
                                rf"skills|skills i taught you){_TAIL}", re.I)),
    # Night Shift report. Spellings like "naait shipht riport" are what Devanagari voice text becomes in Roman letters.
    ("info_night", re.compile(rf"^{_POLITE}(?:(?:have you |did you )?(?:prepared? |made |make )?(?:the |my |your |last )?"
                              rf"(?:{_NIGHT} ?{_SHIFT}|{_NIGHT})(?: {_REPORT}| ki {_REPORT}| ka {_REPORT})?(?: ready| bana(?:ya|i))?|"
                              rf"(?:{_NIGHT} ?{_SHIFT}|raat|kal raat)(?: ko| mein| me| ne)? (?:kya|kya kya) (?:kiya|hua|seekha)"
                              rf"(?: tumne)?|(?:tumane |tumne )?(?:kal )?raat (?:ko|mein|me) kya (?:kiya|seekha)|raat ki {_REPORT}|"
                              rf"what did you do (?:last night|at night|overnight)|{_NIGHT} {_REPORT})"
                              rf"(?:\s+(?:batao|bataao|dikhao|dikhaao|sunao|sunaao|do|please))?{_TAIL}", re.I)),
    # Weekly insights (Phase 3b H7).
    ("info_week", re.compile(rf"^{_POLITE}(?:is hafte|iss hafte|is week|iss week|this week|hafte|week)(?: mein| me| ka| ki)? (?:kya kya |kya )?"
                             rf"(?:kiya|kiye|hua|report|insights|summary)(?: batao| dikhao| sunao)?|weekly (?:report|insights|"
                             rf"summary)|what did (?:you|we) do this week|(?:show )?(?:my )?(?:usage )?insights{_TAIL}", re.I)),
    # Background pause by voice too (Phase 3b H2); resuming is typed only (catalog).
    ("bg_pause", re.compile(rf"^{_POLITE}(?:pause (?:the |my |all )?background(?: work| kaam| tasks| jobs)?|background"
                            rf"(?: ka| ke)?(?: kaam| work| tasks| jobs)? (?:pause karo|pause kar do|roko|rok do|band karo|"
                            rf"band kar do))(?:\s+please)?{_TAIL}", re.I)),
    ("bg_status", re.compile(rf"^{_POLITE}(?:is (?:the )?background(?: work| kaam)? paused|background(?: kaam| work)? "
                             rf"(?:status|paused hai|ruka hai|ruka hua hai)){_TAIL}", re.I)),
    # "itna lag kar raha hai" / "laptop slow hai": a complaint about speed -> what is using the PC (night report
    # 2026-10-07: the model stopped planning this). "lag" needs kar/ho, so "accha lag raha hai" (feels good) is not it.
    ("slow_pc", re.compile(rf"^{_POLITE}(?:why is\s+)?(?:(?:mera|meri|my|the|ye|yeh|this)\s+)?"
                           rf"(?:(?:laptop|laipatop|laiptop|pc|pisi|computer|kanpyutar|kampyutar|system)\s+)?"
                           rf"(?:(?:is\s+)?(?:bahut|itna|itana|ita|itni|kitna|kaafi|bohot|bht|very|so|too|really)\s+)?"
                           rf"(?:(?:lag|laig|laag)(?:gy|ging)?\s+(?:kar|ho)\s+(?:raha|rahi|rahe|rha|rhe|rhi)|lag(?:gy|ging)|"
                           rf"(?:slow|slo)(?:\s+(?:chal|ho)\s+(?:raha|rahi|rahe|rha|gaya|gya))?|"
                           rf"(?:hang|haing)\s+(?:ho|kar)\s+(?:raha|rahi|rahe|rha|gaya|gya)|atak\s+(?:raha|rahi|rahe|rha|gaya))"
                           rf"(?:\s+(?:hai|he|h|hain|kyun|kyu|why))*{_TAIL}", re.I)),
    # "<app> download" for an app that is already installed: open it and say so (night report 2026-10-07).
    ("download_app", re.compile(rf"^{_POLITE}(?!.*\b(?:steam|epic|game|on|from|in|se|pe|par|mein)\b)"
                                rf"(?:(?:download|install)\s+(?P<name>[\w .+&'-]{{2,40}}?)|"
                                rf"(?P<name2>[\w .+&'-]{{2,40}}?)\s+(?:download|install)(?:\s+(?:karo|kar do|kardo|"
                                rf"karna|kar))?){_TAIL}", re.I)),
    ("info_reliability", re.compile(rf"^{_POLITE}(?:tum kitni reliable ho|reliability batao|how reliable are you|"
                                    rf"show (?:your |my )?reliability|kitna sahi kaam karti ho){_TAIL}", re.I)),
    ("info_perf", re.compile(rf"^{_POLITE}(?:what(?:'?s| is) (?:the |my )?)?(?:(?:cpu|gpu|processor|laptop|pc|computer)\s+"
                             rf"(?:temperature|temp|heat)|(?:temperature|temp)\s+(?:of|in)\s+(?:my |the )?(?:cpu|gpu|"
                             rf"processor|laptop|pc|computer))(?:\s+(?:kitna hai|kya hai|batao|now|right now))?{_TAIL}",
                             re.I)),
    ("info_gpu", re.compile(rf"^{_POLITE}(?:(?:which|what(?:'?s| is))\s+(?:gpu|graphics card)(?: do i have| is (?:this|in my pc|installed))?(?: and how much vram)?|what(?:'?s| is) my (?:gpu|graphics card)|gpu (?:info|details|kaunsa hai)){_TAIL}", re.I)),
    ("info_windows", re.compile(rf"^{_POLITE}(?:(?:what|which) (?:version of )?windows(?: version)?(?: do i have| is this(?: pc)?(?: running)?| am i (?:on|running))?|windows version(?: kya hai)?|what(?:'?s| is) my windows version){_TAIL}", re.I)),
    ("info_volume", re.compile(rf"^{_POLITE}(?:what(?:'?s| is) (?:the |my )?(?:current )?volume(?: level)?(?: right now)?|current volume(?: level)?|volume (?:kitna|kitni) hai|how loud is (?:it|the volume)){_TAIL}", re.I)),
    ("theme_set", re.compile(rf"^{_POLITE}(?:(?:switch|change|turn|set|put)(?: (?:on|windows|the theme|my pc))? (?:to |into )?(?P<m1>dark|light) (?:mode|theme)(?: on)?|(?:turn |switch )?on (?P<m2>dark|light) mode|(?:enable|use) (?P<m3>dark|light) (?:mode|theme)|(?P<m4>dark|light) mode (?:on )?(?:karo|kar do|lagao|chalu karo|on karo|on kar do|on)){_TAIL}", re.I)),
    ("info_theme", re.compile(rf"^{_POLITE}(?:is (?:dark|light) mode on|is (?:windows|my pc|the pc) (?:using|in|on) (?:dark|light)(?: mode)?(?: or (?:dark|light) mode)?(?: right now)?|which theme(?: is on)?|what(?:'?s| is) the theme|dark mode on hai kya){_TAIL}", re.I)),
    ("info_health", re.compile(rf"^{_POLITE}(?:how(?:'?s| is) my (?:pc|laptop|computer|battery)(?: doing)?|(?:pc|laptop|system) (?:status|health)|(?:what(?:'?s| is) my |check (?:my )?)?(?:battery|ram|memory)(?: level| usage| status| percentage)?|battery kitni hai|ram kitni (?:use|free) hai|how much (?:ram|memory) (?:am i using|is (?:used|free|in use))(?: right now)?){_TAIL}", re.I)),
    ("smalltalk", re.compile(rf"^{_POLITE}(?:hi|hello|hey|namaste|yo)(?:\s+(?:chutku|there|buddy|bhai))?(?:[,!.\s]+(?:how are you(?: doing)?|kaise ho|kya haal hai|what'?s up|sup))?{_TAIL}", re.I)),
    ("smalltalk", re.compile(rf"^{_POLITE}(?:how are you(?: doing)?|kaise ho|kya haal hai|what'?s up|thanks?(?: you)?|thank you(?: so much)?|shukriya|dhanyavaad|good job|well done|nice){_TAIL}", re.I)),
    ("disk_drive", re.compile(rf"^{_POLITE}(?:how much (?:free )?(?:space|storage) is (?:left|free|there) (?:on|in) (?:my |the )?(?P<d1>[a-z])(?::| drive)|how many gb are free (?:on|in) (?:my |the )?(?P<d2>[a-z])(?::| drive)|(?P<d3>[a-z])(?::| drive) (?:mein|me|pe) kitn[ai] (?:jagah|space|storage)(?: khali| bachi)? (?:hai|he)){_TAIL}", re.I)),
    ("net_connected", re.compile(rf"^{_POLITE}am i (?:connected|online)(?: to (?:the )?(?:network|internet|wifi|wi-fi))?(?:\??\s*which adapter is (?:up|connected))?{_TAIL}", re.I)),
    ("games_list", re.compile(rf"^{_POLITE}(?:(?:which|what) games (?:do i have|are)(?: installed)?(?: on (?:this|my) (?:pc|laptop|computer))?|(?:list|show)(?: me)? (?:my|all|the)(?: installed)? games|mere games(?: dikhao| batao)?|kaun ?se games (?:hai|installed hai)){_TAIL}", re.I)),
    ("read_file", re.compile(rf"^{_POLITE}(?:read|open and read|padho|padh(?:\s+ke|\s+kar)?)\s+(?P<path>[a-z]:\\[^?*\x22<>|]{{1,240}}?\.[a-z0-9]{{1,5}})(?P<rest>\s+(?:and|aur|then)\s+.{{1,200}}?)?{_TAIL}", re.I)),
    ("list_folder", re.compile(rf"^{_POLITE}(?:what (?:files|things|items) are (?:there )?in|what'?s in|what is in|list (?:the |all )?(?:files|contents|items) (?:in|of|inside)|show (?:me )?(?:the )?(?:files|contents) (?:in|of))\s+(?P<path>[a-z]:(?:\\[^?*\x22<>|]{{0,240}}?)?)(?:\s+folder)?{_TAIL}", re.I)),
    ("list_folder", re.compile(rf"^{_POLITE}(?P<path>[a-z]:(?:\\[^?*\x22<>|]{{0,240}}?)?)(?:\s+folder)?\s+(?:mein|me|ke andar)\s+(?:kya kya|kya|kaun si files|kaunsi files)\s+(?:hai|hain|he)(?:\s+dikhao)?{_TAIL}", re.I)),
    # "mere desktop pe kitni files hain" / "how many files are in my downloads" / "what's on my desktop": exact counts
    # come from filesystem.list, so no model counts names (it said "5 files" for 3 files + 3 folders, 2026-10-05).
    ("count_folder", re.compile(rf"^{_POLITE}(?:(?:mere|meri|my|the)\s+)?(?P<named>desktop|downloads?|documents?|pictures?|"
                                rf"photos|music|videos?)(?:\s+folder)?\s+(?:pe|par|mein|me|main|ke andar)\s+(?:kitni|kitne|"
                                rf"kya kya|kaun si|kaunsi)\s*(?:files?|cheezein|items?|folders?)?\s+(?:hai|hain|he|h){_TAIL}"
                                rf"|^{_POLITE}(?:how many (?:files|items|things|folders) (?:are |do i have )?(?:there )?(?:in|on)|"
                                rf"what(?:'?s| is| all is) (?:in|on)|list (?:the )?(?:files|items) (?:in|on))\s+(?:my |the )?"
                                rf"(?P<named2>desktop|downloads?|documents?|pictures?|photos|music|videos?)(?:\s+folder)?{_TAIL}",
                                re.I)),
    ("open_windows", re.compile(rf"^{_POLITE}(?:(?:which|what) (?:windows|apps|applications|programs) are (?:open|running)(?: right now| now)?(?:\??\s*just list (?:the )?(?:app )?names)?|what(?:'?s| is) (?:open|running)(?: right now| on my (?:pc|laptop|screen))?|(?:list|show)(?: me)? (?:the |all |my )?(?:open|running) (?:windows|apps|programs)|kaun ?se (?:apps|windows) (?:khule|open|chal rahe) (?:hai|hain)|kya kya (?:khula|open) hai){_TAIL}", re.I)),
    ("displays", re.compile(rf"^{_POLITE}how many (?:displays|monitors|screens)(?: are| do i have)?(?: connected| attached)?{_TAIL}", re.I)),
    ("brightness_status", re.compile(rf"^{_POLITE}(?:what(?:'?s| is) (?:my |the )?(?:screen |current )?brightness(?: level)?(?: right now)?|brightness kitni hai){_TAIL}", re.I)),
    ("installed", re.compile(rf"^{_POLITE}is (?P<a>[a-z0-9 .+-]{{2,40}}?)(?: or (?P<b>[a-z0-9 .+-]{{2,40}}?))? installed(?: on (?:this|my) (?:pc|computer|laptop))?{_TAIL}", re.I)),
    ("installed", re.compile(rf"^{_POLITE}do i have (?P<a>[a-z0-9 .+-]{{2,40}}?)(?: or (?P<b>[a-z0-9 .+-]{{2,40}}?))? installed{_TAIL}", re.I)),
    ("net_check", re.compile(rf"^{_POLITE}(?:is (?:my |the )?(?:internet|wifi|wi-fi|net) (?:working|down|slow|ok|on)|check (?:my |the )?(?:internet|wifi|wi-fi|network|connection|net)(?: connection| speed)?|(?:internet|net|wifi) (?:chal raha hai(?: kya)?|nahi chal raha|slow hai|kyu nahi chal raha|check karo)|why is (?:my )?(?:internet|wifi|net) (?:slow|not working)){_TAIL}", re.I)),
    ("net_ip", re.compile(rf"^{_POLITE}(?:what(?:'?s| is) my (?:ip|ip address)|my ip(?: address)?|mera ip (?:kya hai|batao)){_TAIL}", re.I)),
    ("net_ping", re.compile(rf"^{_POLITE}ping\s+(?P<host>[a-z0-9.-]{{1,253}}){_TAIL}", re.I)),
    ("game_install", re.compile(rf"^{_POLITE}(?:install|download|get)\s+(?P<game>[a-z0-9 :'&.-]{{2,60}}?)\s+(?:on|from|in)\s+steam{_TAIL}", re.I)),
    ("game_install", re.compile(rf"^{_POLITE}steam\s+(?:pe|par|se)\s+(?P<game>[a-z0-9 :'&.-]{{2,60}}?)\s+(?:install|download)\s+karo{_TAIL}", re.I)),
    ("open_folder", re.compile(rf"^{_POLITE}(?:open|show)\s+(?:my\s+|the\s+)?(?P<folder>downloads|documents|desktop|pictures|photos|videos|music)(?:\s+folder)?{_TAIL}", re.I)),
    ("open_folder", re.compile(rf"^{_POLITE}(?P<folder>downloads|documents|desktop|pictures|photos|videos|music)(?:\s+folder)?\s+{_HINDI_OPEN}{_TAIL}", re.I)),
    ("open_drive", re.compile(rf"^{_POLITE}(?:open|show)\s+(?:my\s+|the\s+)?(?P<drive>[a-z])\s*(?::|drive)(?:\s+drive)?{_TAIL}", re.I)),
    ("open_drive", re.compile(rf"^{_POLITE}(?P<drive>[a-z])\s+drive\s+{_HINDI_OPEN}{_TAIL}", re.I)),
    ("find_file", re.compile(rf"^{_POLITE}(?:find|locate|where(?:'s| is))\s+my\s+(?P<query>[a-z0-9 ._-]{{2,60}}?)(?:\s+(?:file|files|document|pdf|photo|photos))?{_TAIL}", re.I)),
    ("find_file", re.compile(rf"^{_POLITE}search\s+my\s+(?:files|pc|computer|laptop|documents)\s+for\s+(?P<query>[a-z0-9 ._-]{{2,60}}?){_TAIL}", re.I)),
    ("find_in_folder", re.compile(rf"^{_POLITE}(?:search|find|look)\s+(?:in\s+|through\s+)?my\s+(?P<folder>downloads|desktop|"
                                  rf"documents|pictures|photos|music|videos)(?:\s+folder)?\s+for\s+(?P<query>[a-z0-9 ._-]{{2,60}}?)"
                                  rf"{_TAIL}", re.I)),
    ("find_file", re.compile(rf"^{_POLITE}(?:meri\s+|mera\s+)?(?P<query>[a-z0-9 ._-]{{2,60}}?)\s+(?:file\s+)?(?:dhundo|dhoondo|kahan hai|kaha hai){_TAIL}", re.I)),
    ("note_add", re.compile(rf"^{_POLITE}(?:(?:make a |take a |add a )?note|todo|to-do|add to (?:my )?(?:list|todo|to-do))\s*[:,-]\s*(?P<text>.{{1,300}}?){_TAIL}", re.I)),
    ("note_add", re.compile(rf"^{_POLITE}(?:make a |take a )?note (?:that |down )(?P<text>.{{1,300}}?){_TAIL}", re.I)),
    ("note_add", re.compile(rf"^{_POLITE}add\s+(?P<text>.{{1,300}}?)\s+to\s+(?:my\s+)?(?:list|to-?do(?: list)?|notes){_TAIL}", re.I)),
    ("note_add", re.compile(rf"^{_POLITE}(?:likh lo|note karo|yaad rakhna)\s*[:,-]?\s*(?P<text>.{{1,300}}?){_TAIL}", re.I)),
    ("note_list", re.compile(rf"^{_POLITE}(?:(?:show|read|what(?:'?s| is) on)\s+(?:me\s+)?(?:my\s+)?(?:list|to-?do(?: list)?|notes)|my (?:to-?do )?list|(?:meri )?list (?:dikhao|batao)){_TAIL}", re.I)),
    ("note_done", re.compile(rf"^{_POLITE}(?:mark\s+(?:item\s+|number\s+|#)?(?P<id>\d{{1,4}})\s+(?:as\s+)?(?P<state>done|complete|completed|not done|undone)|(?:i(?:'ve| have)?\s+)?(?:done|finished) (?:with )?(?:item\s+|number\s+|#)?(?P<id2>\d{{1,4}})|(?P<id3>\d{{1,4}})\s+(?:ho gaya|done)){_TAIL}", re.I)),
    ("image", re.compile(rf"^{_POLITE}(?:describe|explain|what(?:'?s| is) in)\s+(?:this |the )?(?:image|picture|photo|screenshot)?\s*(?P<path>[a-z]:\\[^?*<>|\x22]+?\.(?:png|jpe?g|webp|heic))(?:\s+(?:to me|for me))?{_TAIL}", re.I)),
    ("screen", re.compile(rf"^{_POLITE}(?:what(?:'?s| is) on (?:my |the )?screen|describe (?:my |the )?screen|what am i looking at|screen pe kya hai|ye kya hai screen pe){_TAIL}", re.I)),
    ("audio_out", re.compile(rf"^{_POLITE}(?:switch|change|move|set)\s+(?:the\s+)?(?:audio|sound|output)\s+(?:output\s+)?to\s+(?:my\s+|the\s+)?(?P<device>[a-z0-9 ()-]{{2,60}}?){_TAIL}", re.I)),
    ("audio_out", re.compile(rf"^{_POLITE}(?:use|play (?:sound|audio) (?:through|on))\s+(?:my\s+|the\s+)?(?P<device>headphones?|headset|earphones?|speakers?|tv|airpods|buds){_TAIL}", re.I)),
    ("audio_out", re.compile(rf"^{_POLITE}(?P<device>headphones?|headset|earphones?|speakers?|tv)\s+(?:pe|par|mein|me)\s+(?:sound|audio|awaaz)\s+(?:karo|chalao|bhejo|lagao){_TAIL}", re.I)),
    ("audio_list", re.compile(rf"^{_POLITE}(?:list|show|which)\s+(?:my\s+|the\s+)?(?:audio|sound|playback|output)\s+(?:devices|outputs)(?:\s+(?:do i have|are there))?{_TAIL}", re.I)),
    ("tidy", re.compile(rf"^{_POLITE}(?:organi[sz]e|tidy(?: up)?|clean up|sort)\s+(?:my\s+|the\s+)?(?P<folder>downloads|desktop|documents)(?:\s+folder)?{_TAIL}", re.I)),
    ("tidy", re.compile(rf"^{_POLITE}(?P<folder>downloads|desktop|documents)(?:\s+folder)?\s+(?:saaf karo|organi[sz]e karo|theek karo|tidy karo){_TAIL}", re.I)),
    ("lock", re.compile(rf"^{_POLITE}(?:lock (?:my |the )?(?:pc|computer|laptop|screen)|(?:pc|laptop|screen) lock karo){_TAIL}", re.I)),
    ("remember", re.compile(rf"^{_POLITE}remember (?:that )?(?:my )?(?P<key>[a-z][a-z0-9_ -]{{0,40}}?)\s*(?:=|is|:)\s*(?P<value>.{{1,300}}?){_TAIL}", re.I)),
    ("playing", re.compile(rf"^{_POLITE}(?:what(?:'?s| is) (?:playing|this song)(?: right now| now)?|(?:kaunsa|kya) (?:gaana|song) (?:chal raha|baj raha) (?:hai|he)){_TAIL}", re.I)),
    ("cleanup", re.compile(rf"^{_POLITE}(?:(?:help me |how (?:can|do) i )?free up (?:some )?(?:disk |storage )?space(?: on (?:my )?(?:c(?: drive)?|pc|computer|laptop))?|(?:clean up|cleanup) (?:my )?(?:c(?: drive)?|pc|computer|laptop|disk|storage)|what(?:'?s| is) taking (?:up )?(?:all )?(?:the )?space(?: on (?:my )?(?:c(?: drive)?|pc|computer))?|(?:c drive|storage|space) (?:khali|saaf) karo){_TAIL}", re.I)),
    ("disk", re.compile(rf"^{_POLITE}(?:how much (?:free |disk |storage )?space(?: is)?(?: left| free| there)?(?: on (?:my |the )?(?:pc|computer|laptop|drives?|disks?))?|(?:check |show )?(?:the )?(?:disk|drive|storage) (?:space|usage)|(?:disk|storage|space) kitna (?:bacha|khali) (?:hai|he)|storage (?:check karo|batao)){_TAIL}", re.I)),
    ("log", re.compile(rf"^{_POLITE}(?:what (?:did|have) you (?:do|done)(?P<today> today)?|(?:show )?(?:your |the )?(?:action log|activity log|history of actions)|aaj (?:tumne )?kya kiya){_TAIL}", re.I)),
    ("recent", re.compile(rf"^{_POLITE}(?:what (?:was|am) i working on|(?:show |list )?(?:my )?recent(?:ly changed)? files|(?:main )?kis (?:file )?pe kaam kar raha tha){_TAIL}", re.I)),
    ("routine_save", re.compile(rf"^{_POLITE}(?:save|create|make)\s+(?:a\s+|my\s+)?routine\s+(?:called\s+|named\s+)?(?P<name>[a-z][a-z0-9 -]{{0,29}}?)\s*[:=-]\s*(?P<commands>.+?){_TAIL}", re.I)),
    ("routine_list", re.compile(rf"^{_POLITE}(?:list|show)?\s*(?:my\s+)?routines{_TAIL}", re.I)),
    ("routine_run", re.compile(rf"^{_POLITE}(?:start|begin|run|activate|turn on|switch to)\s+(?:my\s+|the\s+)?(?P<name>[a-z][a-z0-9 -]{{0,29}}?)\s+(?:mode|routine|setup){_TAIL}", re.I)),
    ("routine_run", re.compile(rf"^{_POLITE}(?P<name>[a-z][a-z0-9 -]{{0,29}}?)\s+(?:mode|routine)\s+(?:on|start|chalu|on karo|start karo|chalu karo|shuru karo){_TAIL}", re.I)),
    ("time", re.compile(rf"^{_POLITE}(?:what(?:'?s| is) the time|what time is it|what time it is|(?:abhi\s+)?(?:kitne|kite\s*ne|kitna)\s+baje(?:\s+(?:hai|hain|he))?|(?:abhi\s+)?time kya (?:hai|hua|ho gaya)(?: hai)?(?:\s+abhi)?|abhi (?:kya )?time (?:kya )?(?:hai|hua)|kya time (?:ho gaya|hua) hai|time batao){_TAIL}", re.I)),
    ("search", re.compile(rf"^{_POLITE}(?:search|look up|find)\s+(?:on\s+)?{_SITE}\s+(?:for\s+)?(?P<query>.+?){_TAIL}", re.I)),
    ("search", re.compile(rf"^{_POLITE}(?:search|look up|google)\s+(?:for\s+)?(?P<query>.+?)\s+(?:on|in)\s+{_SITE}{_TAIL}", re.I)),
    ("search", re.compile(rf"^{_POLITE}{_SITE}\s+(?:pe|par|mein|me)\s+(?P<query>.+?)\s+(?:search|dhundo|dhoondo|search karo){_TAIL}", re.I)),
    ("search", re.compile(rf"^{_POLITE}(?:google|search)\s+(?P<query>.+?){_TAIL}", re.I)),
    ("media", re.compile(rf"^{_POLITE}(?P<action>pause|stop|resume|play|next|previous|skip)(?:\s+(?:the\s+)?(?:song|music|track|video|gaana|media))?{_TAIL}", re.I)),
    ("media", re.compile(rf"^{_POLITE}(?:song|music|gaana|gana)\s+(?P<action>roko|rok do|band karo|chalao|chalu karo|agla|next|pichla|previous){_TAIL}", re.I)),
    ("open", re.compile(rf"^{_POLITE}{_OPEN_VERB}\s+(?:the\s+|my\s+)?(?P<name>.+?){_APP_WORDS}{_TAIL}", re.I)),
    ("open", re.compile(rf"^{_POLITE}(?P<name>.+?){_APP_WORDS}\s+{_HINDI_OPEN}{_TAIL}", re.I)),
]
_MEDIA = {"pause": "pause", "stop": "pause", "roko": "pause", "rok do": "pause", "band karo": "pause", "resume": "play",
          "play": "play", "chalao": "play", "chalu karo": "play", "next": "next", "skip": "next", "agla": "next",
          "previous": "previous", "pichla": "previous"}
_NOT_APPS = re.compile(r"\b(?:and|then|after|folder|file|files|document|pdf|window|windows|tabs?|settings? of|wi-?fi|"
                       r"bluetooth|hotspot|internet|airplane mode|flight mode|data)\b|[\\/:]", re.I)

_cache = {"at": 0.0, "apps": None}


def _installed_apps():
    from chutku.tools.everyday import start_apps
    return start_apps()  # shared, self-refreshing copy (see everyday.start_apps)


def _proposal(tool, arguments, purpose, reply, finish=True):
    return {"status": "continue", "reply": reply, "declared_plan": [purpose],
            "next_steps": [{"tool": tool, "arguments": arguments, "purpose": purpose}], "finish": finish}


_SPLIT = re.compile(r"\s*(?:,\s*)?\b(?:and then|and also|then|aur phir|phir|uske baad|and|aur)\b\s*", re.I)
_PRONOUN = re.compile(r"\b(?:it|that|usko|ise|isko)\b", re.I)   # not "use": an English verb more often than "use" (him)


# "... in a new tab" / "new tab mein": open a new tab; "isi tab mein" / "same tab": use the current tab. Without either,
# Chutku reuses the tab it opened last while it is still showing (owner, 2026-10-05).
_NEW_TAB = re.compile(r"[\s,]*\b(?:(?:in|on) (?:a )?new tab|(?:new|naye|naya|nayi) tab(?: (?:mein|me|main|par|pe|kholo))?)\b", re.I)
_SAME_TAB = re.compile(r"[\s,]*\b(?:(?:in )?(?:the )?(?:same|this|current) tab|(?:isi|is|wahi|usi) tab (?:mein|me|main|par|pe))\b",
                       re.I)
BROWSER_TOOLS = frozenset({"web.open", "web.search", "youtube.play"})


def quick_proposal(goal, apps=None):
    """A deterministic proposal for an unambiguous everyday request, with the owner's tab choice applied."""
    from chutku.translit import roman
    goal = roman(goal)
    tab = None
    for choice, pattern in (("new", _NEW_TAB), ("same", _SAME_TAB)):
        if pattern.search(goal):
            tab, goal = choice, " ".join(pattern.sub(" ", goal).split())
            break
    proposal = _quick_proposal(goal, apps)
    if proposal is not None and tab:
        for step in proposal["next_steps"]:
            if step["tool"] in BROWSER_TOOLS:
                step["arguments"]["tab"] = tab
    return proposal


def _quick_proposal(goal, apps=None):
    """A deterministic proposal for an unambiguous everyday request (or a short chain of
    them joined by "and then"/"aur phir"), else None. Hindi script is read as Hinglish ("पिता श्री" -> "pita shri")."""
    single = _single(goal, apps)
    if single is not None:
        return single
    parts = [p for p in _SPLIT.split(" ".join(goal.split())) if p.strip()]
    if not 2 <= len(parts) <= 3:
        return None
    steps, replies, last_app = [], [], None
    for part in parts:
        if last_app and _PRONOUN.search(part):
            part = _PRONOUN.sub(last_app, part)
        proposal = _single(part, apps)
        if proposal is None or not proposal["next_steps"]:
            return None  # only chains where every part is an unambiguous action
        step = proposal["next_steps"][0]
        last_app = step["arguments"].get("name", last_app)
        steps.append(step)
        replies.append(proposal["reply"])
    return {"status": "continue", "reply": " ".join(r for r in replies if r), "declared_plan": [s["purpose"] for s in steps],
            "next_steps": steps[:4], "finish": all(s["tool"] not in {"system.get_time", "web.weather", "web.news"}
                                                    for s in steps)}


_HOWTO = [
    re.compile(r"^\W*how (?:do|can|should) i (?P<q>.+?) (?:in|on|with|using) (?P<app>[a-z][a-z ]{1,25}?)\W*$", re.I),
    re.compile(r"^\W*how to (?P<q>.+?) (?:in|on|with|using) (?P<app>[a-z][a-z ]{1,25}?)\W*$", re.I),
    re.compile(r"^\W*(?P<app>[a-z][a-z ]{1,25}?) (?:mein|me|main|pe|par|pr) (?P<q>.+?) kaise (?P<verb>[a-z]+)"
               r"(?: (?:hain|hai|h|jate hain|jata hai|sakte hain))?\W*$", re.I),
]
_HOWTO_PLAIN = {"karte", "karu", "karun", "karoon", "kare", "karein", "karna", "hota", "hoga", "kiya"}


_UNREAD = re.compile(r"^\W*(?:(?:whatsapp|wa) (?:pe|par|pr|mein|me) )?(?:kitne|kitni|how many) (?:unread|naye|nayi|new)"
                     r" (?:messages?|msgs?|chats?|message aaye)(?: (?:hain|h|he|aaye hain|are there))?"
                     r"(?: (?:on|in) whatsapp| whatsapp (?:pe|par|pr|mein|me))?(?: hain| h)?\W*$", re.I)


def _howto(text):
    """apps.howto arguments for "how do I X in <app>" / "<app> mein X kaise karte hain", else None."""
    from chutku.apps.howto import resolve
    for pattern in _HOWTO:
        found = pattern.match(text)
        if found:
            app = resolve(found.group("app"))
            if app:
                question = found.group("q").strip()
                verb = found.groupdict().get("verb")
                if verb and verb.casefold() not in _HOWTO_PLAIN:
                    question += " " + verb   # "terminal kaise kholte" -> "terminal kholte" (open)
                return {"app": app, "question": question}
    return None


def _app_action(text):
    """A verified app action whose atlas phrase is the whole request (App Mastery A3), else None."""
    try:
        from chutku.apps import phrases
        found = phrases.match(text)
    except (OSError, ValueError):
        return None
    if found is None:
        return None
    tool, arguments, action = found
    done = action.get("done") or f"Ho gaya: {action['title']}."
    for name, value in arguments.items():
        done = done.replace("{" + name + "}", str(value))
    return _proposal(tool, arguments, action["title"], done)


def _control_or_known(text):
    """Phrases that other rules own (reminders "mujhe ... yaad dilana" etc.) are not messages."""
    return bool(re.search(r"\byaad\b|\bremind|\balarm|\btimer", text, re.I))


# "what did we talk about yesterday" / "pichli baar kya kaha tha" / "kal humne kya baat ki" / "show my chat history"
# "offline mode on" / "offline mode chalu karo" / "go offline" / "offline mode band karo" / "online mode on" / "go online"
OFFLINE_SWITCH = re.compile(
    r"\W*(?:(?:turn |switch |put )?(?:on )?offline mode(?: on| chalu karo| on karo| laga do| start karo)?|go offline"
    r"|offline (?:ho jao|chalo|kaam karo)|local mode(?: on)?"
    r"|(?P<off>(?:turn |switch )?(?:off )?offline mode (?:off|band karo|hatao|off karo)|go online|online mode(?: on)?"
    r"|online ho jao|turn off offline mode))\W*", re.I)
MIND_MAP = re.compile(r"\bmind ?map\b|\bmindmap\b|\bdimaag ka (?:naksha|map)\b", re.I)
HISTORY = re.compile(
    r"\b(?:what did (?:we|i) (?:talk|discuss|chat|say)(?: about)?|what did i (?:ask|tell) you"
    r"|(?:pichli|pichhli|last) (?:baar|time) (?:kya|maine kya|humne kya) (?:kaha|bola|baat|pucha|poocha)"
    r"|(?:kal|aaj|parso) (?:humne |maine )?kya (?:baat|baatein|kaha|bola|pucha|poocha)"
    r"|humne kya baat(?:ein)? ki|show (?:my |our )?(?:chat|conversation) history|(?:meri|hamari) (?:chat|baat(?:ein)?) (?:history )?dikhao)",
    re.I)


_HISTORY_WHEN = r"(?P<when>kal|aaj|today|yesterday|pichh?le hafte|is hafte|last week|this week)"
_HISTORY_TOPIC = [
    re.compile(rf"^{_POLITE}what did (?:i|we) (?:say|talk|discuss|chat|tell you)\s+(?:about|regarding|on)\s+(?P<q>.+?)"
               rf"(?:\s+{_HISTORY_WHEN})?{_TAIL}", re.I),
    re.compile(rf"^{_POLITE}(?:{_HISTORY_WHEN}\s+)?(?:humne\s+|maine\s+)?(?P<q>.+?)\s+ke\s+baa?re\s+(?:mein|men|me)\s+"
               rf"(?:kya|kab)\s+(?:kya\s+)?(?:baat|baatein)\s+(?:hui|huyi|ki|kari)(?:\s+th[ai])?{_TAIL}", re.I),
    re.compile(rf"^{_POLITE}(?P<q>.+?)\s+(?:wali|waali|vali)\s+baat\s+(?:dhoondo|dhundo|dikhao|batao){_TAIL}", re.I),
    re.compile(rf"^{_POLITE}(?:search|find)\s+(?:in\s+)?(?:my |our )?(?:chats?|conversations?|chat history|history)\s+"
               rf"for\s+(?P<q>.+?){_TAIL}", re.I),
    re.compile(rf"^{_POLITE}(?:chat history|history|purani baaton)\s+(?:mein|me)\s+(?P<q>.+?)\s+(?:dhoondo|dhundo|"
               rf"search karo|dekho){_TAIL}", re.I),
]
_HISTORY_DAYS = {"kal": 2, "yesterday": 2, "aaj": 1, "today": 1}


# "after party playlist screen pe hai, play karo" / "play After Party from the screen" (owner, 2026-10-08).
_SCREEN_WORDS = r"(?:screen|display|saamne|samne)\s*(?:pe|par|pr|mein|me)"
_ACT = r"(?P<act>play|chalao|chala do|bajao|baja do|laga do|lagao|open|kholo|khol do|click|dabao|daba do)"
_DO = r"(?:\s+(?:karo|kar do|kardo|kr do|krdo|kr|kar|please|it|that|na))*"
_VISIBLE = [
    re.compile(rf"^{_POLITE}(?:jo\s+)?(?P<name>.+?)\s+(?:jo\s+)?{_SCREEN_WORDS}\s+(?:hi\s+)?(?:hai|h|he|dikh (?:raha|rahi)"
               rf"(?: hai)?)?[,.]?\s*(?:usko\s+|use\s+|wo\s+|woh\s+|vo\s+|usse\s+)?{_ACT}{_DO}{_TAIL}", re.I),
    re.compile(rf"^{_POLITE}{_SCREEN_WORDS}\s+(?:jo\s+)?(?P<name>.+?)\s+(?:hai|h|he|dikh (?:raha|rahi)(?: hai)?)[,.]?\s*"
               rf"(?:usko\s+|use\s+|wo\s+|woh\s+|vo\s+)?{_ACT}{_DO}{_TAIL}", re.I),
    re.compile(rf"^{_POLITE}(?:playlist|song|gaana|gana|video|album)\s+{_SCREEN_WORDS}\s+(?:hi\s+)?(?:hai|h|he)\s+"
               rf"(?P<name>.+?)\s+(?:ki|ka|wali|wala)?\s*{_ACT}{_DO}{_TAIL}", re.I),
    # "screen par dekh, meri after party playlist dikh rahi hogi already, uss par click kar" (live, 2026-10-11)
    re.compile(rf"^{_POLITE}{_SCREEN_WORDS}\s+dekh(?:o|iye)?[,.]?\s+(?:meri\s+|mera\s+|mere\s+)?(?P<name>.+?)\s+"
               rf"(?:dikh\s+(?:raha|rahi|rahe)(?:\s+(?:hogi|hoga|honge|hai|h))?|hai|h)(?:\s+already)?[,.]?\s+"
               rf"(?:uss?|usko|use|isko|ise)\s+(?:par\s+|pe\s+|pr\s+)?{_ACT}(?:\s+(?:kar|karo|kar do|kardo|de|do))?{_TAIL}",
               re.I),
    re.compile(rf"^{_POLITE}(?P<act>play|open|click(?: on)?)\s+(?:the\s+)?(?P<name>.+?)\s+(?:that(?:'s| is)\s+|which is\s+)?"
               rf"(?:on|from)\s+(?:the\s+|my\s+)?(?:screen|display){_TAIL}", re.I),
]
_NAME_FILLER = re.compile(r"\b(?:wali|wala|wale|waali|ki|ka|ke|the|playlist|song|gaana|gana|video|album|jo|hi|vo|wo|"
                          r"dekh|dekho|dekhiye|already|meri|mera|mere)\b", re.I)
_MEDIA_WORDS = re.compile(r"\b(?:playlist|song|gaana|gana|album|spotify|music)\b", re.I)


def _spotify_playlist(shown):
    """A Spotify playlist pointed at on screen ("... playlist ..., uss par click kar"): app.spotify.play_playlist
    when the Action Lab has verified it on this PC, else None (the screen tool handles it)."""
    if not shown or shown.get("kind") != "playlist" or shown.get("action") not in {"play", "click"}:
        return None
    if "spotify" not in {shown.get("app"), shown.get("app_if_open")}:
        return None
    try:
        from chutku.app import PROJECT_ROOT
        from chutku.apps.lab import verified
        if not verified(PROJECT_ROOT, "spotify", "play_playlist"):
            return None
    except (OSError, ValueError):
        return None
    name = shown["name"]
    return _proposal("app.spotify.play_playlist", {"name": name}, "Play one of my playlists by its exact name",
                     f"{name} playlist chala di.")


def _visible(text):
    """screen.act_on_visible arguments when the owner points at something already on the screen, else None."""
    for pattern in _VISIBLE:
        found = pattern.match(text)
        if not found:
            continue
        name = " ".join(_NAME_FILLER.sub(" ", found.group("name")).split()).strip(" ,.'\"")
        if not name or len(name) > 80:
            return None
        act = found.group("act").casefold()
        action = "play" if act in {"play", "chalao", "chala do", "bajao", "baja do", "laga do", "lagao"} else \
            "open" if act in {"open", "kholo", "khol do"} else "click"
        arguments = {"name": name, "action": action}
        kind = re.search(r"\b(playlist|song|gaana|gana|album|video)\b", text, re.I)
        if kind:   # "After Party playlist" is not the song "After Party" (owner, 2026-10-08)
            arguments["kind"] = {"gaana": "song", "gana": "song"}.get(kind.group(1).casefold(), kind.group(1).casefold())
        if re.search(r"\bspotify\b", text, re.I) or (action == "play" and _MEDIA_WORDS.search(text)):
            arguments["app"] = "spotify"
        elif action == "play" or arguments.get("kind") in {"playlist", "album"}:
            arguments["app_if_open"] = "spotify"   # music is usually Spotify: read only its window when it is open
        return arguments
    return None


def _history_topic(text):
    """{"query": topic, "days"?: n} when the owner asks what was said about a topic, else None."""
    for pattern in _HISTORY_TOPIC:
        found = pattern.match(text)
        if found:
            query = " ".join(found.group("q").split()).strip(" ?.!'\"")
            from chutku.history_index import terms
            if not query or len(query) > 120 or not terms(query):
                return None   # no topic word left ("what did we talk about"): the day summary answers that
            when = (found.groupdict().get("when") or "").casefold()
            days = _HISTORY_DAYS.get(when, 7 if "hafte" in when or "week" in when else None)
            return {"query": query} | ({"days": days} if days else {})
    return None


def _done(reply):
    return {"status": "done", "reply": reply, "declared_plan": [], "next_steps": [], "finish": True}


_REWIND_MINUTES = re.compile(
    rf"^{_POLITE}(?:(?:pichh?le|pichh?li|last|past)\s+(?P<n>\d{{1,4}})\s*(?P<unit>minutes?|mins?|min|ghante|ghanta|"
    rf"hours?|hrs?)\s+(?:ka|ki|ke|mein|me)?\s*(?:sab(?:\s+kuch)?|everything|saara kaam|jo bhi kiya)\s+"
    rf"(?:wapas|vapas|undo)\s*(?:karo|kar do|kr do|krdo)?|undo everything (?:you did )?(?:in|from|for) the "
    rf"(?:last|past) (?P<n2>\d{{1,4}})\s*(?P<unit2>minutes?|mins?|hours?|hrs?)){_TAIL}", re.I)
_REWIND_TODAY = re.compile(rf"^{_POLITE}(?:aaj (?:jo (?:bhi )?kiya|ka) sab(?: kuch)? (?:wapas|vapas|undo)(?: karo| kar do)?|"
                           rf"undo everything (?:you did )?today){_TAIL}", re.I)
_REWIND_TASK = re.compile(rf"^{_POLITE}(?:last task (?:undo|wapas)(?: karo| kar do)?|(?:pichhla|pichla|last) (?:task|kaam) "
                          rf"(?:poora |pura )?(?:wapas|vapas|undo)(?: karo| kar do)?|undo (?:the )?(?:whole )?last task)"
                          rf"{_TAIL}", re.I)
_REWIND_PREVIEW = re.compile(rf"^{_POLITE}(?:rewind preview|(?:pichh?le|last) (?P<n>\d{{1,4}}) (?:minutes?|mins?|min) "
                             rf"(?:ka|mein|me) kya kya wapas ho sakta hai|what would (?:a )?rewind (?:of|for) (?:the )?last "
                             rf"(?P<n2>\d{{1,4}}) (?:minutes?|mins?) undo){_TAIL}", re.I)


_WHEN = (r"(?:abhi|abhi abhi|thodi der pehle|just now|earlier|kal|aaj|parso|yesterday|today|this|last week|"
         r"pichh?le hafte)(?:\s+(?:subah|dopahar|shaam|sham|raat|morning|afternoon|evening|night))?")
_TIMELINE = [
    re.compile(rf"^{_POLITE}(?:wo|woh|vo|that)\s+(?P<q>.+?)\s+jo\s+(?:maine\s+)?(?P<when>{_WHEN})\s+(?:khola|kholi|"
               rf"dekha|dekhi|padha|padhi|open kiya|open ki)\s+th[ai]\b.*$", re.I),
    re.compile(rf"^{_POLITE}(?P<when>{_WHEN})?\s*(?:maine\s+)?(?:kaunsa|kaun sa|kaun si|kaunsi|konsa|konsi)\s+"
               rf"(?P<q>.+?)\s+(?:khola|kholi|dekha|dekhi|padha|padhi|open kiya|open ki)\s+th[ai](?:\s+maine)?{_TAIL}",
               re.I),
    re.compile(rf"^{_POLITE}which\s+(?P<q>.+?)\s+did i\s+(?:open|have open|look at|read)(?:\s+(?P<when>{_WHEN}|this "
               rf"morning|this evening|yesterday evening|yesterday morning))?{_TAIL}", re.I),
    re.compile(rf"^{_POLITE}what was i (?:looking at|reading)\s+(?P<when>{_WHEN}|yesterday evening|this morning)"
               rf"(?P<q>){_TAIL}", re.I),
]


def _timeline(text):
    """"wo PDF jo kal shaam khola tha" / "abhi kaunsa PDF khola tha" / "which pdf did I open yesterday" (S21)."""
    for pattern in _TIMELINE:
        found = pattern.match(text)
        if found:
            query = " ".join((found.group("q") or "").split())[:120]
            arguments = {"query": query} | ({"when": found.group("when").strip()} if found.group("when") else {})
            return _proposal("timeline.search", arguments, f"Look up {query or 'what was open'} in the timeline",
                             "", finish=False)
    return None


def _rewind(text):
    """"pichhle 5 minute ka sab wapas karo" / "aaj jo kiya sab wapas" / "last task undo karo" (Causal Rewind, S18)."""
    from datetime import datetime, timedelta
    found = _REWIND_PREVIEW.match(text)
    if found:
        minutes = int(found.group("n") or found.group("n2"))
        return _proposal("rewind.preview", {"minutes": minutes}, f"Show what the last {minutes} minutes' rewind "
                         "would undo", "", finish=False)
    found = _REWIND_MINUTES.match(text)
    if found:
        n, unit = int(found.group("n") or found.group("n2")), (found.group("unit") or found.group("unit2")).casefold()
        minutes = n * 60 if unit.startswith(("h", "g")) else n
        if not 1 <= minutes <= 10080:
            return None
        now = datetime.now().replace(microsecond=0)
        return _proposal("rewind.run", {"since": (now - timedelta(minutes=minutes)).isoformat(),
                                        "until": now.isoformat()}, f"Undo everything from the last {n} {unit}",
                         "", finish=False)
    until = datetime.now().replace(microsecond=0).isoformat()   # nothing newer than the list the owner approves
    if _REWIND_TODAY.match(text):
        return _proposal("rewind.run", {"today": True, "until": until}, "Undo everything from today", "",
                         finish=False)
    if _REWIND_TASK.match(text):
        return _proposal("rewind.run", {"last_task": True, "until": until}, "Undo the whole last task", "",
                         finish=False)
    return None


def _single(goal, apps=None):
    text = " ".join(goal.split())
    app_action = _app_action(text)
    if app_action is not None:
        return app_action
    if _UNREAD.match(text):
        return _proposal("message.unread_count", {}, "Count unread WhatsApp chats", "", finish=False)
    howto = _howto(text)
    if howto is not None:
        return _proposal("apps.howto", howto, f"Look up how to {howto['question']} in {howto['app']}", "", finish=False)
    rewind = _rewind(text)
    if rewind is not None:
        return rewind
    remembered = _timeline(text)
    if remembered is not None:
        return remembered
    from chutku import control_intent
    control = control_intent.kind(text)
    if control == "undo":
        return _proposal("log.undo", {}, "Undo the last change", "Undid the last change.")
    if control == "recent":
        return _proposal("log.recent", {"limit": 3}, "List what Chutku just did", "", finish=False)
    if control == "help":
        return _done(control_intent.HELP_TEXT)
    if control == "presence":
        return _done("Haan, main yahin hoon. Bolo!")
    if control == "repeat":
        previous = control_intent.last_goal()
        if previous is None:
            return _done("There is nothing to repeat yet.")
        again = _single(previous, apps)
        if again is None or not again["next_steps"]:
            return None  # the model plans the previous request again
        return again
    if control == "resume":
        return _done("Main chalu hi hoon. Bolo, kya karna hai?")   # (a real pause is lifted by the dashboard)
    if control in ("stop", "pause") and not re.fullmatch(r"\W*stop\W*", text, re.I):
        return _done("Nothing is running right now.")  # (the dashboard stops running work before this point)
    scheduled = _scheduled(text)
    if scheduled is not None:
        return scheduled
    from chutku.message_intent import parse_send
    message = parse_send(text)
    if message is not None:
        app = {"whatsapp": "WhatsApp", "telegram": "Telegram"}[message["app"]]
        return _proposal("message.send", message, f"Send a {app} message to {message['to']}",
                         f"Message for {message['to']} on {app}: “{message['text']}”.",
                         finish=False)
    from chutku.message_intent import parse_open_chat, parse_read_chat, parse_tell
    told = parse_tell(text)
    if told is not None and not _control_or_known(text):
        return _proposal("message.send", told, f"Send a WhatsApp message to {told['to']}",
                         f"Message for {told['to']} on WhatsApp: “{told['text']}”.", finish=False)
    reading = parse_read_chat(text)
    if reading is not None:  # "Pita Shri ne kya bola?" / "did mammi reply?"
        return _proposal("message.read_chat", reading, f"Read the chat with {reading['to']}", "", finish=False)
    chat = parse_open_chat(text)
    if chat is not None:  # "search Pita Shri in WhatsApp": open that chat, then ask what to send (owner, 2026-10-04)
        return _proposal("message.open_chat", chat, f"Open {chat['to']}'s chat on WhatsApp", "", finish=False)
    from chutku.daily_intent import parse_daily
    daily = parse_daily(text)
    if daily is not None:
        tool, arguments, purpose, reply, finish = daily
        return _done(reply) if not tool else _proposal(tool, arguments, purpose, reply, finish=finish)
    from chutku.browser_intent import parse_browser
    browsed = parse_browser(text)
    if browsed is not None:
        tool, arguments, purpose, reply, finish = browsed
        return _proposal(tool, arguments, purpose, reply, finish=finish)
    offline = OFFLINE_SWITCH.fullmatch(text)
    if offline:
        on = not offline.group("off")
        return _proposal("settings.offline_mode", {"on": on}, "Switch offline mode " + ("on" if on else "off"),
                         "Offline mode is on: I'll use only my local models, nothing goes to Gemini." if on else
                         "Offline mode is off: Gemini is back as my backup when the internet works.")
    if MIND_MAP.search(text):
        return _proposal("mind.map", {}, "Open your mind map", "Opened your mind map.")
    shown = _visible(text)
    playlist = _spotify_playlist(shown)
    if playlist is not None:   # a Spotify playlist: the lab-verified way (Your Library, exact name, check it plays)
        return playlist
    if shown is not None:   # it is already on the screen: act on that exact item, never search (2026-10-08)
        return _proposal("screen.act_on_visible", shown, f"{shown['action'].capitalize()} '{shown['name']}' from the "
                         "screen", "", finish=False)
    topic = _history_topic(text)
    if topic is not None:   # a topic search ("DBMS ke baare mein kya baat hui"), Phase 3b H4
        return _proposal("history.search", topic, f"Search past chats for {topic['query']}", "", finish=False)
    if HISTORY.search(text):
        from chutku import recall
        day = recall.day_from_words(text)
        said = recall.talked_about(day)
        return _done(said or f"I have no saved conversation from {day.strftime('%d %b')}. (Conversations are "
                             "remembered from 2026-10-04 on.)")
    from chutku import learning
    rating = learning.parse_feedback(text)
    if rating is not None:
        return _proposal("mind.feedback", {"rating": rating}, "Remember how the last task went",
                         "Thanks! I'll keep doing it that way." if rating == "good" else
                         "Sorry about that. I won't reuse that approach; tell me what you wanted and I'll do it right.")
    event = learning.parse_event(text)
    if event is not None:
        name, item = event
        return _proposal("mind.add", {"list": name, "text": item}, "Remember a date",
                         f"Noted in your schedule: {item}. I'll remind you as it gets close.")
    from chutku.mind_intent import parse_mind
    remembered = parse_mind(text)
    if remembered is not None:
        tool, arguments, purpose, reply, finish = remembered
        return _proposal(tool, arguments, purpose, reply, finish=finish)
    from chutku.file_intent import parse_file_batch, parse_file_command
    batch = parse_file_batch(text)
    if batch is not None:
        return {"status": "continue", "reply": "", "declared_plan": [s["purpose"] for s in batch], "next_steps": batch,
                "finish": False}
    filed = parse_file_command(text)
    if filed is not None:
        tool, arguments, purpose, reply = filed
        return _proposal(tool, arguments, purpose, reply)
    from chutku.input_intent import parse_input
    pressed = parse_input(text)
    if pressed is not None:
        tool, arguments, purpose, reply = pressed
        return _proposal(tool, arguments, purpose, reply)
    for kind, pattern in PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        if kind == "build":
            what = match.group("what").strip(" .'\"")
            if not 3 <= len(what) <= 1500 or re.search(r"[\\/:]|\binto\b|program files", text, re.I):
                # a path or "write X into Y" is a file task, not a software build: let the model plan it
                return None
            from chutku.agent_loop import projects_folder
            words = [w for w in re.findall(r"[a-z0-9]+", what.casefold()) if w not in _SLUG_STOP][:3]
            folder = projects_folder() + "\\" + ("-".join(words) or "project")[:40]
            return _proposal("code.build_project", {"request": f"Build {what}", "path": folder},
                             f"Build {what} in {folder}", f"Built {what}.")
        if kind == "close":
            name = match.group("name").strip(" '\"").casefold()
            if name in {"gaana", "gana", "song", "music", "video", "media", "the song", "the music"}:
                return _proposal("media.control", {"action": "pause"}, "Media: pause", "Paused the media.")
            if name in {"tab", "this tab", "the tab", "current tab"}:
                return _proposal("keyboard.edit", {"action": "close_tab"}, "Close the tab", "Closed the tab.")
            if name in {"it", "this", "that", "window", "this window", "all", "everything", "computer", "pc", "laptop",
                        "sab", "sabhi", "saare", "sab kuch", "sabko", "all apps", "everything open", "all windows"}:
                return None  # unclear target, or a power request: let the model ask
            if len(name) < 2 or _NOT_APPS.search(name):
                return None
            return _proposal("apps.quit", {"name": match.group("name").strip(" '\"")}, f"Close {match.group('name')}",
                             f"Closed {match.group('name')}.")
        if kind in ("volume", "brightness"):
            word = (match.groupdict().get("dir1") or match.groupdict().get("dir2") or match.groupdict().get("dir3")
                    or ("up" if match.groupdict().get("up") is not None else "down" if match.groupdict().get("down") is not None else "")).lower()
            direction = "down" if word in {"down", "kam", "kam karo", "dheere karo"} else "up"
            arguments = {"action": direction}
            if match.groupdict().get("step"):
                arguments["step"] = int(match.group("step"))
            tool = "audio.volume" if kind == "volume" else "display.brightness"
            noun = "volume" if kind == "volume" else "brightness"
            return _proposal(tool, arguments, f"Turn the {noun} {direction}", f"Turned the {noun} {direction}.")
        if kind in ("volume_set", "brightness_set"):
            level = int(match.group("level"))
            if not 0 <= level <= 100:
                return None
            tool, noun = ("audio.volume", "volume") if kind == "volume_set" else ("display.brightness", "brightness")
            return _proposal(tool, {"action": "set", "level": level}, f"Set {noun} to {level}", f"Set the {noun} to {level}%.")
        if kind == "mute":
            action = match.group("what").lower()
            return _proposal("audio.volume", {"action": action}, action.capitalize(), f"{action.capitalize()}d the sound.")
        if kind in ("remind_in", "timer"):
            minutes = int(match.group("n")) * (60 if match.group("unit").lower().startswith(("h", "g")) else 1)
            message = (match.groupdict().get("message") or "Your timer is done.").strip(" '\"")
            if not 1 <= minutes <= 525600:
                return None
            label = "timer" if kind == "timer" else "reminder"
            return _proposal("reminder.set", {"message": message[:200], "in_minutes": minutes},
                             f"Set a {minutes}-minute {label}", f"Okay, I'll remind you in {minutes} minutes.")
        if kind == "remind_at":
            from datetime import datetime, timedelta
            hour, minute = int(match.group("h")), int(match.group("m") or 0)
            ampm = (match.group("ampm") or "").lower()
            if ampm == "pm" and hour < 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None
            if not ampm and 1 <= hour <= 6:
                hour += 12   # the owner's everyday meaning, as in "5 baje" (daily_intent._at): 1-6 is afternoon/evening
            now = datetime.now()
            when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if match.group("day") or match.group("day2"):
                when += timedelta(days=1)
            elif when <= now:
                if ampm or hour >= 13:
                    when += timedelta(days=1)
                else:
                    return None  # "at 5" already passed today: am or pm? let the model ask
            message = match.group("message").strip(" '\"")
            return _proposal("reminder.set", {"message": message[:200], "at": when.strftime("%Y-%m-%dT%H:%M")},
                             "Set a reminder", f"Okay, I'll remind you on {when.strftime('%A at %I:%M %p')}.")
        if kind == "briefing":
            steps = [{"tool": "system.get_time", "arguments": {}, "purpose": "Read the time"},
                     {"tool": "web.weather", "arguments": {}, "purpose": "Check the weather"},
                     {"tool": "reminder.list", "arguments": {}, "purpose": "Check upcoming reminders"},
                     {"tool": "web.news", "arguments": {"count": 5}, "purpose": "Get top headlines"}]
            return {"status": "continue", "reply": "", "declared_plan": ["Time, weather, reminders and news"],
                    "next_steps": steps, "finish": False}
        if kind == "play":
            query = match.group("query").strip(" '\"")
            return _proposal("youtube.play", {"query": query}, f"Play {query} on YouTube", f"Started “{query}” on YouTube.")
        if kind == "weather":
            city = (match.groupdict().get("city") or "").strip(" '\"")
            if re.search(r"\b(?:cpu|gpu|processor|laptop|pc|computer|battery)\b", city, re.I):
                # "temperature of my cpu" is not a city's weather
                return _proposal("system.performance", {}, "Check CPU, GPU, memory and temperature", "", finish=False)
            return _proposal("web.weather", {"city": city} if city else {}, "Check the weather", "", finish=False)
        if kind == "news":
            topic = (match.groupdict().get("topic") or "").strip(" '\"")
            return _proposal("web.news", {"topic": topic} if topic else {}, "Get the latest headlines", "", finish=False)
        if kind == "time":
            return _proposal("system.get_time", {}, "Read the clock", "", finish=False)
        if kind == "routine_save":
            commands = [c.strip(" '\".") for c in re.split(r"\s*[,;]\s*", match.group("commands")) if c.strip()]
            name = " ".join(match.group("name").split())
            return _proposal("routine.save", {"name": name, "commands": commands[:6]}, f"Save the {name} routine",
                             f"Your {name} routine: {', '.join(commands[:6])}. Say “start {name} mode” to run it.")
        if kind == "routine_list":
            return _proposal("routine.list", {}, "List routines", "", finish=False)
        if kind == "routine_run":
            from chutku.routines import steps_for
            name = " ".join(match.group("name").split())
            steps = steps_for(name)
            if not steps:
                return None  # unknown routine: let the model handle it
            return {"status": "continue", "reply": f"Starting {name} mode.", "declared_plan": [f"Run the {name} routine"],
                    "next_steps": steps, "finish": True}
        if kind == "smalltalk":
            said = text.casefold()
            if any(word in said for word in ("thank", "shukriya", "dhanyavaad", "good job", "well done", "nice")):
                reply = "Anytime! Aur kuch?"
            else:
                reply = "Main badhiya hoon! Bolo, kya karna hai?"
            return {"status": "done", "reply": reply, "declared_plan": [], "next_steps": [], "finish": True}
        if kind == "disk_drive":
            return _proposal("system.disk_space", {}, "Check free space on every drive", "", finish=False)
        if kind == "net_connected":
            if not re.search(r"\b(?:adapter|wi-?fi|ethernet|lan)\b", text, re.I):
                return _proposal("net.check", {}, "Check the internet connection", "", finish=False)
            steps = [{"tool": "net.check", "arguments": {}, "purpose": "Check the internet connection"},
                     {"tool": "network.status", "arguments": {}, "purpose": "List the network adapters"}]
            return {"status": "continue", "reply": "", "declared_plan": [s["purpose"] for s in steps],
                    "next_steps": steps, "finish": False}
        if kind == "games_list":
            return _proposal("games.list", {}, "List the installed games", "", finish=False)
        if kind == "read_file":
            # Read the real text first; the answer ("the first task", a summary) is then written from it.
            return _proposal("file.extract_text", {"path": match.group("path")}, f"Read {match.group('path')}", "",
                             finish=False)
        if kind == "list_folder":
            path = match.group("path").rstrip(" \\.")
            path = path + "\\" if re.fullmatch(r"[a-z]:", path, re.I) else path
            return _proposal("filesystem.list", {"path": path}, f"List {path}", "", finish=False)
        if kind == "count_folder":
            import os
            name = (match.group("named") or match.group("named2")).casefold()
            folder = {"desktop": "Desktop", "download": "Downloads", "downloads": "Downloads", "document": "Documents",
                      "documents": "Documents", "picture": "Pictures", "pictures": "Pictures", "photos": "Pictures",
                      "music": "Music", "video": "Videos", "videos": "Videos"}[name]
            path = os.path.join(os.environ.get("USERPROFILE", "C:\\Users\\Public"), folder)
            return _proposal("filesystem.list", {"path": path}, f"List your {folder}", "", finish=False)
        if kind == "open_windows":
            return _proposal("windows.list", {}, "List the open windows", "", finish=False)
        if kind == "displays":
            return _proposal("screen.displays", {}, "Count the displays", "", finish=False)
        if kind == "brightness_status":
            return _proposal("display.brightness_status", {}, "Check the brightness", "", finish=False)
        if kind == "installed":
            names = [n.strip() for n in (match.group("a"), match.group("b")) if n and n.strip()]
            if any(n.casefold() in {"it", "this", "that", "everything", "anything"} for n in names):
                return None
            steps = [{"tool": "apps.installed", "arguments": {"query": n}, "purpose": f"Check whether {n} is installed"}
                     for n in names]
            return {"status": "continue", "reply": "", "declared_plan": [s["purpose"] for s in steps],
                    "next_steps": steps, "finish": False}
        if kind == "theme_set":
            mode = next(match.group(g) for g in ("m1", "m2", "m3", "m4") if match.group(g)).casefold()
            return _proposal("settings.theme_set", {"mode": mode}, f"Switch Windows to {mode} mode",
                             f"Switched to {mode} mode.")
        if kind == "bg_pause":
            return _proposal("background.pause", {}, "Pause background work", "Background work is paused: "
                             "scheduled tasks and the Night Shift wait until you type \"resume background work\".")
        if kind == "bg_status":
            return _proposal("background.status", {}, "Check whether background work is paused", "", finish=False)
        if kind == "slow_pc":
            if len(match.group(0).split()) < 2:
                return None   # a bare "slow" / "lagging" is not clearly about the PC
            return _proposal("system.performance", {}, "Check what is slowing the PC: CPU, memory, temperature, "
                             "top programs", "", finish=False)
        if kind == "download_app":
            wanted = (match.group("name") or match.group("name2") or "").strip(" '\"")
            from chutku.tools.everyday import resolve_app
            try:
                app = resolve_app({"name": wanted}, apps if apps is not None else _installed_apps())
            except (ValueError, OSError):
                return None   # not installed (or unclear): the model decides how to get it
            return _proposal("apps.launch", {"name": app["name"]}, f"Open {app['name']} (already installed)",
                             f"{app['name']} is already installed, so I opened it.")
        if kind.startswith("info_"):
            tool, purpose = {"info_gpu": ("system.gpu_status", "Check the GPU"),
                             "info_windows": ("system.environment", "Check the Windows version"),
                             "info_volume": ("system.volume_status", "Check the volume"),
                             "info_theme": ("settings.theme_status", "Check the theme"),
                             "info_health": ("system.health", "Check battery, memory and disk"),
                             "info_perf": ("system.performance", "Check CPU, GPU, memory and temperature"),
                             "info_reliability": ("ledger.summary", "Check how often each action really worked"),
                             "info_learned": ("reflex.list", "List the request shapes learned as instant skills"),
                             "info_night": ("nightshift.report", "Read last night's Night Shift report"),
                             "info_week": ("insights.week", "Count this week's requests and actions")}[kind]
            return _proposal(tool, {}, purpose, "", finish=False)
        if kind in {"net_check", "net_ip"}:
            return _proposal("net.check", {}, "Check the internet connection", "", finish=False)
        if kind == "net_ping":
            host = match.group("host").casefold()
            host = {"google": "google.com", "youtube": "youtube.com"}.get(host, host)
            return _proposal("net.ping", {"host": host}, f"Ping {host}", "", finish=False)
        if kind == "game_install":
            game = " ".join(match.group("game").split())
            return _proposal("games.install", {"name": game}, f"Install {game} from Steam",
                             f"Steam's install window for {game} is open: choose the drive (D: has the most space) "
                             "and click Install.")
        if kind == "find_in_folder":
            import os
            home = os.environ.get("USERPROFILE")
            folder = {"photos": "Pictures"}.get(match.group("folder").casefold(), match.group("folder").capitalize())
            query = match.group("query").strip(" .")
            if not home or _ORDERING.search(query):
                return None
            return _proposal("files.find", {"path": os.path.join(home, folder), "query": query},
                             f"Find files named like {query} in {folder}", "", finish=False)
        if kind in {"open_folder", "open_drive", "find_file"}:
            import os
            home = os.environ.get("USERPROFILE")
            if kind == "open_drive":
                drive = match.group("drive").upper() + ":\\"
                return _proposal("files.open", {"path": drive}, f"Open the {drive[0]}: drive", f"Opened {drive[0]}: drive.")
            if not home:
                return None
            if kind == "open_folder":
                folder = {"photos": "Pictures"}.get(match.group("folder").casefold(), match.group("folder").capitalize())
                return _proposal("files.open", {"path": os.path.join(home, folder)}, f"Open {folder}", f"Opened {folder}.")
            query = match.group("query").strip(" .")
            if _ORDERING.search(query):
                return None  # ordering words need the model (filesystem.search with a sort)
            if query.casefold() in {"files", "file", "pc", "computer", "laptop", "phone", "keys", "glasses", "mind"}:
                return None
            return _proposal("files.find", {"path": home, "query": query}, f"Find files named like {query}", "",
                             finish=False)
        if kind == "note_add":
            text = match.group("text").strip(" '\"")
            return _proposal("note.add", {"text": text}, "Add to your list", f"Added to your list: {text}.") if text else None
        if kind == "note_list":
            return _proposal("note.list", {}, "Read your list", "", finish=False)
        if kind == "note_done":
            number = int(match.group("id") or match.group("id2") or match.group("id3"))
            done = (match.group("state") or "done").casefold() not in {"not done", "undone"}
            return _proposal("note.done", {"id": number, "done": done}, f"Mark item {number} {'done' if done else 'open'}",
                             f"Item {number} marked {'done' if done else 'not done'}.")
        if kind == "image":
            return _proposal("image.describe", {"path": match.group("path").strip()}, "Look at the image", "",
                             finish=False)
        if kind == "screen":
            return _proposal("screen.understand", {"when": "hotkey_moment"}, "Look at the screen", "", finish=False)
        if kind == "audio_out":
            device = " ".join(match.group("device").split())
            return _proposal("audio.set_output", {"device": device}, f"Switch sound to {device}",
                             f"Sound now plays through {device}.")
        if kind == "audio_list":
            return _proposal("audio.outputs", {}, "List playback devices", "", finish=False)
        if kind == "tidy":
            import os
            folder = match.group("folder").capitalize()
            home = os.environ.get("USERPROFILE")
            if not home:
                return None
            return _proposal("files.organize", {"path": os.path.join(home, folder)}, f"Tidy your {folder} folder",
                             f"Tidied {folder} into Images, Documents, Videos, Music, Archives, Installers and Code. "
                             "To put them back, ask “what did you do today” and undo that action number.")
        if kind == "lock":
            return _proposal("system.lock", {}, "Lock the PC", "Locked the PC.")
        if kind == "remember":
            key = re.sub(r"[^a-z0-9_-]+", "_", match.group("key").strip().casefold()).strip("_")[:64]
            value = match.group("value").strip(" '\".")
            if not key or not key[0].isalpha() or not value:
                return None
            return _proposal("memory.remember", {"key": key, "value": value}, f"Remember {key}",
                             f"Memory: {key} = {value}.")
        if kind == "playing":
            return _proposal("media.status", {}, "Check what is playing", "", finish=False)
        if kind == "cleanup":
            import os
            home = os.environ.get("USERPROFILE")
            return _proposal("storage.cleanup_report", {"path": home} if home else {}, "Find space to free on your drive",
                             "", finish=False)
        if kind == "disk":
            return _proposal("system.disk_space", {}, "Check free space on every drive", "", finish=False)
        if kind == "log":
            today = {"today": True} if match.group("today") or "aaj" in text.casefold() else {}
            return _proposal("log.recent", today, "List what Chutku did", "", finish=False)
        if kind == "recent":
            import os
            home = os.environ.get("USERPROFILE")  # routes to the grant that holds the user's folders
            return _proposal("files.recent", {"path": home} if home else {}, "Find recently changed files", "",
                             finish=False)
        if kind == "search":
            if _IN_APP.search(text):
                return None  # "search X in WhatsApp / in Spotify" is not a Google search (live session 2026-10-04)
            query = re.sub(r"^(?:for|about)\s+", "", match.group("query").strip(" '\"“”"), flags=re.I).strip(" '\"“”")
            site = _SITES.get((match.groupdict().get("site") or "google").lower(), "google")
            if not query or len(query) > 300:
                return None
            label = {"youtube": "YouTube", "maps": "Google Maps"}.get(site, site.capitalize())
            return _proposal("web.search", {"query": query, "site": site}, f"Search {label} for {query}",
                             f"Searched {label} for “{query}”.")
        if kind == "media":
            action = _MEDIA.get(match.group("action").lower())
            if action is None:
                return None
            return _proposal("media.control", {"action": action}, f"Media: {action}",
                             {"pause": "Paused the media.", "play": "Resumed the media.", "next": "Skipped to the next track.",
                              "previous": "Went back to the previous track."}[action])
        name = match.group("name").strip(" '\"")
        if _DOMAIN.match(name) and " " not in name:
            url = name if name.lower().startswith(("http://", "https://")) else "https://" + name
            return _proposal("web.open", {"url": url}, f"Open {name}", f"Opened {name}.")
        if not name or len(name) > 80 or _NOT_APPS.search(name) or re.search(r"\s(?:in|on|with|using|mein|pe)\s", name, re.I):
            return None  # "youtube.com in brave browser" is not an app name
        from chutku.tools.everyday import resolve_app
        try:
            app = resolve_app({"name": name}, apps if apps is not None else _installed_apps())
        except (ValueError, OSError):
            # Not one exact Start-menu name ("vs code", "word", or two apps fit): apps.launch asks Windows search,
            # like the owner would, and opens the first result that is an installed app.
            if not re.fullmatch(r"[\w .+&'-]{2,60}", name) or name.casefold() in {"it", "this", "that", "everything", "all"} \
                    or len(name.split()) > 3:
                return None   # longer phrases are not app names: the model reads them
            return _proposal("apps.launch", {"name": name}, f"Open {name}", f"Opened {name}.")
        return _proposal("apps.launch", {"name": app["name"]}, f"Open {app['name']}", f"Opened {app['name']}.")
    return _follow_up(text)


_TASKS_LIST = re.compile(rf"^{_POLITE}(?:(?:show|list|what are) (?:my |the )?scheduled tasks|what(?:'?s| is) scheduled|"
                         rf"scheduled tasks(?: dikhao| batao)?|kya kya schedule(?:d)? (?:hai|kiya hai)|"
                         rf"schedule(?:d)? (?:kya hai|dikhao|batao)){_TAIL}", re.I)
_TASKS_CANCEL = re.compile(rf"^{_POLITE}(?:cancel|stop|delete|remove|band karo|hatao)?\s*(?:all |sab |saare |sare )?"
                           rf"(?:the |my )?scheduled tasks?(?: (?P<id>[0-9a-f]{{6}}))?\s*(?:cancel karo|band karo|hatao|"
                           rf"cancel kar do|band kar do|rok do|ruk jao)?{_TAIL}", re.I)


def _scheduled(text):
    """"30 min baad X", "har 15 min X", "12 baje X": save the order; "scheduled tasks dikhao" / "... cancel karo"."""
    if _TASKS_LIST.match(text):
        return _proposal("task.list", {}, "List the scheduled tasks", "", finish=False)
    cancel = _TASKS_CANCEL.match(text)
    if cancel and re.search(r"cancel|stop|delete|remove|band|hatao|rok|ruk", text, re.I):
        arguments = {"id": cancel.group("id")} if cancel.group("id") else {"all": True}
        return _proposal("task.cancel", arguments, "Cancel scheduled tasks", "Cancelled the scheduled task"
                         + ("." if cancel.group("id") else "s."))
    from chutku import scheduled
    found = scheduled.parse(text)
    if found is None:
        return None
    from datetime import datetime
    arguments = {"goal": found["goal"], "at": found["at"].strftime("%Y-%m-%dT%H:%M:%S")}
    if found["every_minutes"]:
        arguments["every_minutes"] = found["every_minutes"]
    summary = scheduled.describe({"goal": found["goal"], "next_at": arguments["at"],
                                  "every_minutes": found["every_minutes"]})
    return _proposal("task.schedule", arguments, f"Schedule: {found['goal'][:80]}",
                     f"Theek hai, yaad rakh liya: {summary}. Tab tak main normal kaam karti rahungi.")


def _follow_up(text):
    """Last resort, only when nothing else matched: "hi bhej do" within 2 minutes of opening a chat."""
    from chutku.message_intent import parse_follow_up_send
    from chutku.tools.apps_extra import recent_chat
    recent = recent_chat()
    body = parse_follow_up_send(text) if recent is not None else None
    if body is None:
        return None
    return _proposal("message.send", {"app": recent[0], "to": recent[1], "text": body},
                     f"Send a WhatsApp message to {recent[1]}", f"Message for {recent[1]}: “{body}”.", finish=False)


def _say_time(out):
    return f"It's {out['local_time']}."


def _say_disk(out):
    parts = [f"{d['drive'][0]}: has {d['free_gb']} GB free of {d['total_gb']} GB ({d['free_percent']}%)"
             for d in out["drives"]]
    return "; ".join(parts) + "." + (" " + out["advice"] if out.get("advice") else "")


def _say_recent(out):
    if not out["files"]:
        where = ", ".join(Path(folder).name or folder for folder in out["searched"])
        return f"No files changed in the last {out['days']} days in {where}."
    names = ", ".join(f"{f['name']} ({f['modified'][5:]})" for f in out["files"][:5])
    return f"Most recently changed: {names}."


def _say_log(out):
    if not out["actions"]:
        return "I haven't done anything yet." if out["chain_ok"] else "My action log is damaged; run doctor."
    shown = [f"#{a['id']} {a['tool']} {a['state'].lower().replace('_', ' ')}" for a in out["actions"][:6]]
    return f"{out['count']} action(s), newest first: " + "; ".join(shown) + "."


def _say_routines(out):
    if not out["routines"]:
        return "No routines yet. Try: save routine work: open VS Code, play lofi on YouTube, set volume to 30."
    return " ".join(f"{name}: {', '.join(commands)}." for name, commands in out["routines"].items())


def _say_cleanup(out):
    if not out["suggestions"]:
        return f"Nothing big to clear on {out['drive'][0]}: right now."
    return (f"Here's where you can free space on {out['drive'][0]}: " + "; ".join(out["suggestions"]) +
            ". This was only a look: your files are untouched. Tell me which to recycle, or open Disk Cleanup for temp files.")


def _say_playing(out):
    title = out.get("title") or (out.get("now_playing") or {}).get("title")
    artist = out.get("artist") or (out.get("now_playing") or {}).get("artist")
    if not title:
        return "Nothing is playing right now."
    return f"“{title}”" + (f" by {artist}" if artist else "") + " is playing."


def _say_outputs(out):
    names = [d["name"] + (" (in use)" if d["default"] else "") for d in out["devices"]]
    return "Playback devices: " + ", ".join(names) + "."


def _say_image(out):
    return out["description"]


def _say_screen(out):
    return out.get("answer") or out.get("summary") or "I looked, but couldn't describe the screen."


def _say_notes(out):
    open_items = [f"{i['id']}. {i['text']}" for i in out["items"] if not i["done"]]
    if not open_items:
        return "Your list is empty." if not out["items"] else "Everything on your list is done."
    return f"{len(open_items)} on your list: " + "; ".join(open_items[:8]) + "."


def _say_found(out):
    if not out["matches"]:
        return f"I couldn't find a file named like “{out['query']}” in your personal folders."
    shown = "; ".join(f"{m['name']} (in {m['folder']}, {m['modified'][:10]})" for m in out["matches"][:5])
    more = f" and {out['count'] - 5} more" if out["count"] > 5 else ""
    return f"Found {out['count']}: {shown}{more}."


def _say_net(out):
    ip = f" Your IP is {out['local_ip']} on this network" + (f", {out['public_ip']} on the internet." if out.get("public_ip")
                                                               else ".") if out.get("local_ip") else ""
    return out["verdict"] + ip


def _say_ping(out):
    if out.get("unknown_host"):
        return f"There's no site called {out['host']}."
    if not out["received"]:
        return f"{out['host']} didn't answer any of {out['sent']} pings."
    return (f"{out['host']} answered {out['received']} of {out['sent']} pings"
            + (f", average {out['average_ms']} ms." if out.get("average_ms") is not None else "."))


def _say_message(out):
    if out.get("seen_in_chat"):
        return f"Done: “{out['text']}” is now in your {out['app']} chat with {out['to']}." + (
            " " + out["tip"] if out.get("tip") else "")
    return f"I pressed send in {out['app']} for {out['to']}, but couldn't see the message in the chat. Please check."


def _say_reliability(out):
    """Earned autonomy in plain words: how often checked actions worked, and what keeps failing."""
    if not out.get("actions_measured"):
        return "Nothing measured yet: every step that changes something is checked and counted as it runs."
    count = out["actions_measured"]
    text = (f"Of {count} checked action{'' if count == 1 else 's'}, {out['worked']} really worked "
            f"({round(out['rate'] * 100)}%).")
    weak = out.get("keeps_failing") or []
    if weak:
        text += " Keeps failing, so it asks you first: " + "; ".join(
            f"{w['tool']} on {w['target']} ({w['passes']}/{w['trials']})" for w in weak[:3]) + "."
    else:
        text += " Nothing keeps failing right now."
    return text


def _say_timeline(out):
    if out.get("note"):
        return out["note"]
    matches = out["matches"]   # strict: an unexpected shape lets the model answer instead of a wrong fixed reply
    if not matches:
        return ("Nothing like that in the timeline for that time." if out["recording"]
                else "The timeline is off, so I don't know. Type 'timeline on' to let me remember window titles.")
    first = matches[0]
    text = f"{first['title']} ({first['app']}, {first['at']})"
    if len(matches) > 1:
        text += ". Also: " + "; ".join(f"{m['title']} ({m['at']})" for m in matches[1:4])
    return text + "."


def _say_rewind(out):
    """rewind.preview / rewind.run in plain words."""
    if "undone" not in out:
        return out.get("summary") or "Nothing to undo."
    text = out.get("summary") or ""
    if out.get("skipped_conflict"):
        text += " Kept as you changed them: " + "; ".join(s.rstrip(".") for s in out["skipped_conflict"][:3]) + "."
    if out.get("irreversible"):
        text += " Cannot be undone: " + "; ".join(out["irreversible"][:3]) + "."
    if out.get("failed"):
        text += " Failed: " + "; ".join(out["failed"][:3]) + "."
    return text


def _say_tasks(out):
    tasks = out.get("tasks") or []
    if not tasks:
        return "Nothing is scheduled right now."
    return f"{len(tasks)} scheduled: " + "; ".join(f"{t['summary']} (id {t['id']})" for t in tasks[:6]) + "."


def _say_visible(out):
    """screen.act_on_visible (2026-10-08)."""
    if out.get("playing"):
        now = f" Now playing: {out['now_playing']}" + (f" by {out['artist']}" if out.get("artist") else "") + "." \
            if out.get("now_playing") else ""
        return f"Played “{out['clicked']}” from the screen.{now}"
    if "play_button" in out:
        return f"Opened “{out['clicked']}”, but it is not playing yet. " + (out.get("error") or "")
    return f"Clicked “{out['clicked']}” on the screen."


def _say_week(out):
    """Weekly insights (Phase 3b H7)."""
    from chutku.insights import say
    return say(out)


def _say_history(out):
    """Past chats about a topic (Phase 3b H4)."""
    found = out.get("matches") or []
    topic = " ".join(out.get("terms") or []) or out.get("query", "")
    if not found:
        return f"I found nothing about “{topic}” in our past chats."
    lines = [f"{m['date']}: you said “{m['said'][:90]}”" + (f", I said “{m['reply'][:90]}”" if m.get("reply") else "")
             for m in found[:3]]
    return f"About “{topic}” ({len(found)} found): " + "; ".join(lines) + "."


def _say_background(out):
    if not out.get("paused"):
        return "Background work is running normally (scheduled tasks and the Night Shift)."
    since = f" since {str(out['since'])[:16].replace('T', ' ')}" if out.get("since") else ""
    return (f"Background work is paused{since}: scheduled tasks and the Night Shift are waiting. "
            "Type \"resume background work\" to start them again.")


def _say_night(out):
    """Last night's Night Shift report in plain words."""
    if not out.get("ran"):
        return out.get("summary") or "Night Shift has not run yet."
    counts = out.get("counts") or {}
    text = (f"Night Shift ran on {out.get('date')} ({str(out.get('started', ''))[11:16]}–"
            f"{str(out.get('finished', ''))[11:16]}): {out.get('new_skills', 0)} new instant skills; re-checked "
            f"{out.get('requests_rechecked', 0)} of your past requests: {counts.get('same', 0)} same, "
            f"{counts.get('changed', 0)} changed, {counts.get('fails now', 0)} now failing.")
    if out.get("fails_now"):
        text += " Now failing: " + "; ".join(f"\"{g}\"" for g in out["fails_now"][:3]) + "."
    if out.get("keeps_failing"):
        text += " Keeps failing: " + ", ".join(out["keeps_failing"][:3]) + "."
    if out.get("jobs_failed"):
        text += " Jobs that failed: " + ", ".join(out["jobs_failed"]) + "."
    return text + f" Fine-tune data: {out.get('fine_tune')}."


def _say_learned(out):
    """Learned instant skills (master plan S17) in plain words."""
    def share(value):
        return "–" if value is None else f"{round(value * 100)}%"
    week = (f" Instant answers this week: {share(out.get('instant_this_week'))} "
            f"(last week {share(out.get('instant_last_week'))}).")
    skills = out.get("skills") or []
    if not skills:
        return ("Nothing learned yet: when you ask the same kind of thing twice in different words and it works, "
                "I learn to do it instantly." + week)
    active = [s for s in skills if s.get("enabled")]
    text = f"I learned {len(skills)} skill{'' if len(skills) == 1 else 's'} ({len(active)} on): " + "; ".join(
        f"\"{s['phrase']}\" ({s['passes']}/{s['hits']} worked)" if s.get("enabled") else f"\"{s['phrase']}\" (off)"
        for s in skills[:5]) + "."
    return text + week


def _say_gpu(out):
    return "; ".join(f"{g['name']} with {round(int(g['vram_mib']) / 1024)} GB video memory ({int(g['vram_mib'])} MB, "
                     f"driver {g['driver_version']})" for g in out["gpus"]) + "."


def _say_adapters(out):
    parts = []
    for adapter in out["adapters"]:
        status = str(adapter.get("Status", "")).casefold()
        state = "up" if status == "up" else "disconnected" if "disconnect" in status else status or "unknown"
        speed = f", {adapter['LinkSpeed']}" if state == "up" and adapter.get("LinkSpeed") else ""
        parts.append(f"{adapter.get('Name', 'adapter')} is {state}{speed}")
    return ("; ".join(parts) + ".") if parts else "No network adapters found."


def _say_environment(out):
    build = int(str(out["windows_version"]).split(".")[-1] or 0)
    name = "Windows 11" if build >= 22000 else "Windows 10"
    drives = ", ".join(f"{d['drive']} {d['free_gib']} GB free" for d in out.get("drives", []))
    return f"{name} (build {out['windows_version']}, {out['machine']})." + (f" Drives: {drives}." if drives else "")


def _say_volume(out):
    return "Sound is muted." if out.get("muted") else f"Volume is at {out['level']}%."


def _say_theme(out):
    return f"Apps use {out['apps']} mode and Windows uses {out['system']} mode."


def _say_health(out):
    parts = []
    power = out.get("battery")
    if power:
        parts.append(f"battery {power['percent']}%" + (" and charging" if power["charging"] else " on battery power"))
    if out.get("memory"):
        parts.append(f"RAM {out['memory']['used_percent']}% used ({out['memory']['free_gb']} GB free)")
    parts += [f"{d['drive'][0]}: {d['free_gb']} GB free" for d in out.get("disk", [])]
    low = [d["drive"][0] + ":" for d in out.get("disk", []) if d.get("low")]
    return ("Your PC: " + ", ".join(parts) + "." + (f" Low space on {', '.join(low)}." if low else ""))


def _say_perf(out):
    """CPU, RAM, GPU and what uses the most memory: the instant answer to "laptop lag kar raha hai"."""
    parts = []
    if out.get("cpu_percent") is not None:
        parts.append(f"CPU {round(out['cpu_percent'])}%")
    memory = out.get("memory") or {}
    if memory:
        parts.append(f"RAM {memory['used_percent']}% used ({memory['used_gib']} of {memory['total_gib']} GB)")
    gpu = out.get("gpu") or {}
    if gpu.get("utilization_percent") is not None:
        parts.append(f"GPU {gpu['utilization_percent']}%" + (f" at {gpu['temperature_c']}°C" if gpu.get(
            "temperature_c") is not None else ""))
    text = "Your PC: " + ", ".join(parts) + "." if parts else "I could not read the PC's load."
    totals = {}
    for process in out.get("top_memory_processes") or []:   # several "Code" windows are one app
        totals[process["name"]] = totals.get(process["name"], 0) + process["memory_mib"]
    if totals:
        label = {"llama-server": "my local brain (llama-server)", "MsMpEng": "Windows Defender", "Code": "VS Code"}
        top = sorted(totals.items(), key=lambda item: -item[1])[:3]
        text += " Using the most memory: " + ", ".join(
            f"{label.get(name, name)} {mib / 1024:.1f} GB" for name, mib in top) + "."
    hints = []
    if memory.get("used_percent", 0) >= 85:
        hints.append("RAM is almost full; closing one of those apps would help most")
    if (out.get("cpu_percent") or 0) >= 85:
        hints.append("the CPU is very busy right now")
    if gpu.get("temperature_c") and gpu["temperature_c"] >= 85:
        hints.append("the GPU is hot")
    return text + (" " + "; ".join(hints).capitalize() + "." if hints else "")


def _describe_person(person):
    extra = [f"aka {', '.join(person['aliases'])}" if person.get("aliases") else "",
             person.get("relation") or "", f"WhatsApp chat “{person['whatsapp']}”" if person.get("whatsapp") else "",
             "number saved" if person.get("phone") else ""]
    return person["name"] + (" (" + "; ".join(e for e in extra if e) + ")" if any(extra) else "")


def _say_who(out):
    if not out["known"]:
        return (f"I don't know who {out['name']} is yet. Tell me, e.g. “UB is my {out['name']}”, "
                f"or “{out['name']} ka number +91… hai”.")
    return f"{out['name']} is {_describe_person(out['person'])}."


def _say_mind(out):
    parts = []
    if out.get("people"):
        parts.append("People: " + "; ".join(_describe_person(p) for p in out["people"][:15]) + ".")
    if out.get("facts"):
        parts.append("About you: " + "; ".join(f"{k}: {v}" for k, v in list(out["facts"].items())[:15]) + ".")
    for name, items in (out.get("lists") or {}).items():
        if not items:
            parts.append(f"Your {name} list is empty.")
            continue
        shown = "; ".join(f"{i['id']}. {i['text']}" + (" (done)" if i.get("done") else "") for i in items[:15])
        parts.append(f"{name.capitalize()}: {shown}.")
    if parts and out.get("memory_meter"):
        parts.append(out["memory_meter"])   # how much of it fits in one prompt (Phase 3b H3)
    return " ".join(parts) or "I don't know anything about you yet. Tell me: “UB is my gf”, “my home is in Pune”, " \
                              "“add assignment: DBMS report by Friday”."


def _say_games(out):
    if not out["games"]:
        return "I don't see any Steam or Epic games on this PC."
    shown = ", ".join(f"{g['name']} ({g['store']}" + (f", {g['state']})" if g.get("state") != "installed" else ")")
                      for g in out["games"][:12])
    return f"{out['count']} game{'s' if out['count'] != 1 else ''}: {shown}."


# Windows' own background windows, not apps the owner opened (seen live 2026-10-04).
_SHELL_WINDOWS = {"program manager", "windows input experience", "nvidia geforce overlay", "microsoft text input application",
                  "windows shell experience host", "search", "start", "task view", "chutku", "default ime", "msctfime ui"}


def _app_of(window):
    """'lofi - YouTube - Personal - Microsoft Edge' -> 'Microsoft Edge'; '(6) WhatsApp' -> 'WhatsApp'."""
    title = (window.get("title") or "").replace("\u200b", "").strip()
    name = title.rsplit(" - ", 1)[-1].strip() if " - " in title else title
    name = re.sub(r"^\(\d+\)\s*", "", name) or Path(window.get("executable") or "").stem   # unread counts
    return None if name.casefold() in _SHELL_WINDOWS else name


def _say_listing(out):
    entries = out.get("entries") or []
    if not entries:
        return f"{out['path']} is empty."
    if "file_count" in out:   # exact counts from the tool, files and folders told apart
        def part(label, names):
            if not names:
                return ""
            shown = ", ".join(names[:15]) + (f" and {len(names) - 15} more" if len(names) > 15 else "")
            return f"{len(names)} {label}{'s' if len(names) != 1 else ''} ({shown})"
        pieces = [p for p in (part("file", out.get("files") or []), part("folder", out.get("folders") or [])) if p]
        return f"{out['path']} has " + " and ".join(pieces) + "."
    shown = ", ".join(entries[:25]) + (f", and {len(entries) - 25} more" if len(entries) > 25 else "")
    return f"{len(entries)} item{'s' if len(entries) != 1 else ''} in {out['path']}: {shown}."


def _say_windows(out):
    apps = list(dict.fromkeys(_app_of(w) for w in out["windows"] if _app_of(w)))
    if not apps:
        return "No app windows are open."
    return f"{len(apps)} app{'s' if len(apps) != 1 else ''} open: " + ", ".join(apps[:15]) + "."


def _say_read_chat(out):
    who = out["to"]
    if not out["messages"]:
        text = f"I opened {who}'s chat but couldn't read any text messages (photos and voice notes can't be read)."
    else:
        said = "; ".join(("You" if m["from"] == "you" else who) + ": " + m["text"][:120] for m in out["messages"][-4:])
        last = out["messages"][-1]
        lead = f"{who} replied" if last["from"] == "them" else f"No reply yet from {who} after your last message"
        text = f"{lead}. Latest: {said}."
    if out.get("sync_warning"):
        text += " " + out["sync_warning"]
    return text


def _say_open_chat(out):
    return f"{out['to']}'s chat is open on WhatsApp. What should I send?"


def _say_displays(out):
    shown = ", ".join(f"{d['width']}x{d['height']}" + (" (main)" if d.get("primary") else "") for d in out["displays"])
    return f"{out['count']} display{'s' if out['count'] != 1 else ''} connected: {shown}."


def _say_brightness(out):
    return f"Screen brightness is at {out['level']}%."


def _say_installed(out):
    query = out.get("query") or "that app"
    if not out["apps"]:
        return f"{query} isn't installed (not in the Start menu)."
    return f"Yes, {query}: " + ", ".join(app["name"] for app in out["apps"][:4]) + "."


# Quick tools whose failures are final (no device, no such routine...): report them instead of re-planning.
FINAL_ERROR_TOOLS = frozenset({"audio.set_output", "audio.outputs", "system.disk_space", "files.recent",
                               "storage.cleanup_report", "routine.save", "routine.list", "log.recent",
                               "image.describe", "note.done", "note.add", "files.find", "files.open",
                               "games.install", "message.send", "message.open_chat", "message.read_chat", "settings.theme_set", "apps.launch", "filesystem.list",
                               "file.extract_text", "mind.person", "mind.add",
                               "mind.done", "mind.fact", "mind.feedback", "mind.map", "settings.offline_mode"})


# Instant spoken answers for the quick tier's own observation tools (no model round needed).
def _say_howto(out):
    from chutku.apps.howto import say
    return say(out)


def _say_unread(out):
    from chutku.apps.extras import say_unread
    return say_unread(out)


QUICK_ANSWERS = {"apps.howto": _say_howto, "message.unread_count": _say_unread, "screen.act_on_visible": _say_visible, "insights.week": _say_week, "history.search": _say_history, "background.status": _say_background, "nightshift.report": _say_night, "timeline.search": _say_timeline, "rewind.preview": _say_rewind, "rewind.run": _say_rewind, "task.list": _say_tasks, "reflex.list": _say_learned, "ledger.summary": _say_reliability, "system.get_time": _say_time, "system.disk_space": _say_disk, "files.recent": _say_recent,
                 "log.recent": _say_log, "routine.list": _say_routines,
                 "storage.cleanup_report": _say_cleanup, "media.status": _say_playing,
                 "audio.outputs": _say_outputs,
                 "image.describe": _say_image, "screen.understand": _say_screen,
                 "note.list": _say_notes, "files.find": _say_found,
                 "net.check": _say_net, "net.ping": _say_ping,
                 "message.send": _say_message, "system.gpu_status": _say_gpu,
                 "system.environment": _say_environment, "system.volume_status": _say_volume,
                 "settings.theme_status": _say_theme, "system.health": _say_health, "system.performance": _say_perf,
                 "screen.displays": _say_displays, "display.brightness_status": _say_brightness,
                 "apps.installed": _say_installed, "games.list": _say_games,
                 "mind.who": _say_who, "mind.show": _say_mind, "windows.list": _say_windows,
                 "network.status": _say_adapters, "filesystem.list": _say_listing,
                 "message.open_chat": _say_open_chat, "message.read_chat": _say_read_chat}


def quick_answer(session):
    """A final answer when the only step was one completed quick observation, else None."""
    import json
    if not session.steps:
        return None
    if any(step["state"] != "COMPLETED" for step in session.steps):
        return None
    proposal = quick_proposal(session.goal)
    if proposal is None:
        return None
    routine = proposal["declared_plan"][:1] and proposal["declared_plan"][0].startswith("Run the ")
    if len(session.steps) > 1 and not routine and not all(step["tool"] in QUICK_ANSWERS for step in session.steps):
        return None
    parts = []
    for step in session.steps:
        formatter = QUICK_ANSWERS.get(step["tool"])
        if formatter is None:
            if not routine:
                return None
            parts.append(step["purpose"] + " ✓")
            continue
        try:
            data = json.loads(step["observation"])
            if isinstance(data, dict) and set(data) == {"untrusted_data", "source"} and data["source"] == step["tool"]:
                # Outside text is wrapped for the planner (S15; instruction-like lines already removed). The instant
                # answer only shows the owner what was read, so it formats the data inside.
                data = data["untrusted_data"]
            parts.append(formatter(data))
        except (ValueError, KeyError, TypeError, IndexError):
            return None  # truncated or unexpected output: let the model answer
    return (proposal["reply"] + " " if routine else "") + " ".join(parts)


class QuickPlanner:
    """Planner facade: the first round for unambiguous requests, and instant answers for its observations."""

    @staticmethod
    def final_error(session):
        """A clear refusal when a quick step failed with an error that retrying cannot fix."""
        if len(session.steps) != 1 or session.steps[0]["state"] != "FAILED":
            return None
        step = session.steps[0]
        if step["tool"] not in FINAL_ERROR_TOOLS or quick_proposal(session.goal) is None or not step.get("message"):
            return None
        return "I couldn't do that: " + step["message"]

    name = "quick"

    def propose(self, session, runtime, check=None):
        from chutku.agent_loop import validate_proposal
        if session.steps:
            reply = quick_answer(session)
            status = "done"
            if reply is None:
                reply, status = self.final_error(session), "clarify"
            if reply is None:
                raise LookupError("no quick answer")
            raw = {"status": status, "reply": reply[:600], "declared_plan": [], "next_steps": [], "finish": True}
        else:
            raw = quick_proposal(session.goal)
        if raw is None:
            raise LookupError("no quick intent")
        allowed = {tool.name for tool in runtime.registry.list()}
        return validate_proposal(raw, runtime, allowed), {"planner": self.name, "seconds": 0, "backend": "rules"}
