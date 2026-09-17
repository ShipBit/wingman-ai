"""Words the fuzzy correction must never touch.

A vocabulary entry like "Para" is one edit away from "part", "pare", "park".
Those are words people say in every other sentence; turning them into a
planet name would be worse than any misspelling. So the correction leaves a
word alone when it is one of the common words of the languages we ship, and
only an explicit `heard=correct` pair may override that.

The lists are short on purpose: function words, pronouns, the most common
verbs and nouns. They are not dictionaries; a rare word is still corrected.
"""

_ENGLISH = """
the be to of and a in that have i it for not on with he as you do at this but his by
from they we say her she or an will my one all would there their what so up out if
about who get which go me when make can like time no just him know take people into
year your good some could them see other than then now look only come its over think
also back after use two how our work first well way even new want because any these
give day most us are was were been has had did does done said went made came took
gave got saw knew put let run set show try ask need feel seem leave call keep hold
turn bring begin help start move play pay hear meet stand lose add change fall cut
open part park pare pair port pass past path pack plan place point power press
price print proof pull push pure push rest right room round route rule safe same
send sent sense serve ship shot side sign site size skip slow small sold sort sound
space speak speed spot star stay step stop store story sure talk team tell term test
text than thing three through today told tool top total touch town track trade true
trust under until upon very view wait walk want watch water week where while white
whole wide wife will wind wish with word world write wrong yes yet young
area areas station stations system systems status ship ships cargo fuel power
engine engines shield shields weapon weapons target targets scan scanner map
route course speed thrust land landing take off gear door doors light lights
mode modes quantum jump drive travel trip mission missions contract contracts
money credits price prices buy sell trade market terminal location locations
planet planets moon moons orbit station city cities base bases outpost outpots
hangar dock docking pad pads gate gates zone zones sector sectors distance
report reports message messages channel signal contact contacts enemy enemies
friend friends crew pilot pilots captain commander officer group team member
number numbers name names list lists item items thing things kind type types
level levels order orders check checks state states data info information
question answer problem problems reason reasons idea ideas case cases
morning evening night minute minutes hour hours second seconds moment
hand hands head eye eyes face body arm arms leg legs foot feet heart
house home road street car train plane boat sea land sky sun earth fire
water air wind rain snow ice stone rock metal glass paper book
mother father son daughter brother sister child children man men woman women
boy girl baby family friend people person life live love money job school
company business office market service services program computer machine
food drink bread meat fish fruit milk coffee tea wine beer sugar salt
red blue green yellow black white grey brown orange pink dark bright
hot cold warm cool dry wet hard soft heavy light fast slow loud quiet
early late near far inside outside above below front behind left right
east west north south always often sometimes rarely never again already
almost also always another anything before between both each either enough
every everything few little many much neither nothing several such through
together toward without within
"""

_GERMAN = """
der die das und ist ich du er sie es wir ihr sie nicht ein eine einer eines einem
einen zu auf in mit von für den dem des im am um an aus bei nach über unter vor
hinter neben zwischen durch gegen ohne bis seit auch noch schon nur so wie was wer
wo wann warum wenn dann als ob dass weil aber oder doch mal ja nein bitte danke gut
sehr mehr viel wenig alle alles nichts etwas jetzt hier dort da hin her mich dich
sich uns euch mein dein sein ihr unser euer haben hat hatte sind war waren wird
werden wurde kann konnte muss musste soll sollte will wollte darf mag möchte machen
mache macht gehen geht kommen kommt sehen sieht sagen sagt geben gibt nehmen nimmt
finden bringen lassen halten stehen liegen bleiben fahren fliegen öffnen schließen
zeigen setzen stellen legen laufen warten suchen spielen hören lesen wissen denken
glauben heute morgen gestern immer nie oft bald wieder schnell langsam groß klein
neu alt lang kurz hoch tief weit nah rechts links oben unten vorne hinten start
stopp halt weiter zurück ende anfang seite platz punkt zeit tag welt wort arbeit
mir dir ihm ihn ihnen dies diese dieser dieses jede jeder jedes kein keine keinen
man denn dazu davon damit dabei darum daran darauf dafür dagegen wozu sonst eben
ganz fast etwa gerade genau eigentlich vielleicht natürlich ziemlich überhaupt
"""

_SPANISH = """
el la los las un una unos unas de del a al en con por para sin sobre entre hasta
desde y o pero si no que cual quien como cuando donde porque muy mas menos todo
nada algo este esta esto ese esa eso aquel yo tu el ella nosotros ellos ellas me te
se nos le les mi tu su ser soy es son era fue estar estoy esta hay haber tener tengo
tiene poder puede querer quiero hacer hace ir voy va ver dar decir dice saber sabe
llegar pasar deber poner parecer quedar creer hablar llevar dejar seguir encontrar
llamar venir pensar salir volver tomar conocer vivir sentir tratar mirar contar
empezar esperar buscar existir entrar trabajar escribir perder producir ocurrir
entender pedir recibir recordar terminar permitir aparecer conseguir comenzar
servir sacar necesitar mantener resultar leer caer cambiar presentar crear abrir
considerar oir acabar convertir ganar formar traer partir morir aceptar realizar
suponer comprender lograr explicar preguntar tocar reconocer estudiar alcanzar
nacer dirigir correr utilizar pagar ayudar gustar jugar escuchar cumplir ofrecer
descubrir levantar intentar usar decidir repetir olvidar valer parar para
"""

_FRENCH = """
le la les un une des de du au aux et ou mais donc or ni car que qui quoi dont où
je tu il elle on nous vous ils elles me te se nous vous lui leur mon ma mes ton ta
tes son sa ses notre nos votre vos ce cet cette ces ça ceci cela y en ne pas plus
jamais rien personne aucun tout tous toute toutes très trop peu beaucoup bien mal
ici là oui non si dans sur sous avec sans pour par vers chez entre avant après
pendant depuis jusque comme quand pourquoi comment être suis est sont était avoir
ai as a ont avait faire fais fait font dire dis dit aller vais va vont voir vois
voit savoir sais sait pouvoir peux peut vouloir veux veut venir viens vient devoir
dois doit prendre prends prend trouver donner parler aimer passer mettre demander
tenir sembler laisser rester penser entendre regarder répondre rendre connaître
paraître arriver croire attendre vivre sortir porter montrer commencer suivre
perdre revenir écrire ouvrir jouer appeler tomber garder monter lire finir entrer
courir arrêter arrête stop attention maintenant aujourd'hui demain hier toujours
encore déjà bientôt vite lentement grand petit nouveau vieux long court haut bas
loin près droite gauche devant derrière début fin côté place point temps jour
monde mot travail
"""


def _words(block: str) -> frozenset[str]:
    return frozenset(w for w in block.split() if w)


PROTECTED_WORDS: frozenset[str] = _words(_ENGLISH) | _words(_GERMAN) | _words(_SPANISH) | _words(_FRENCH)
