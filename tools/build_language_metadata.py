"""Generate matching local/browser language inventories from pinned library data."""
import json
from pathlib import Path

DATA={
'ar':('Арабский','مرحبا. هذا اختبار للصوت.'),'bg':('Болгарский','Здравейте. Това е проверка на гласа.'),
'bn':('Бенгальский','নমস্কার। এটি কণ্ঠস্বরের পরীক্ষা।'),'ca':('Каталанский','Hola. Això és una prova de veu.'),
'cs':('Чешский','Dobrý den. Toto je zkouška hlasu.'),'cy':('Валлийский','Helo. Prawf llais yw hwn.'),
'da':('Датский','Hej. Dette er en stemmetest.'),'de':('Немецкий','Hallo. Dies ist ein Sprachtest.'),
'el':('Греческий','Γεια σας. Αυτή είναι μια δοκιμή φωνής.'),'en':('Английский','Hello. This is a voice test.'),
'es':('Испанский','Hola. Esta es una prueba de voz.'),'et':('Эстонский','Tere. See on hääleproov.'),
'eu':('Баскский','Kaixo. Hau ahots proba bat da.'),'fa':('Персидский','سلام. این یک آزمایش صدا است.'),
'fi':('Финский','Hei. Tämä on äänitesti.'),'fr':('Французский','Bonjour. Ceci est un test de voix.'),
'he':('Иврит','שלום. זו בדיקת קול.'),'hi':('Хинди','नमस्ते। यह आवाज़ का परीक्षण है।'),
'hu':('Венгерский','Helló. Ez egy hangteszt.'),'hy':('Армянский','Բարեւ։ Սա ձայնի փորձարկում է։'),
'id':('Индонезийский','Halo. Ini adalah uji suara.'),'is':('Исландский','Halló. Þetta er raddpróf.'),
'it':('Итальянский','Ciao. Questa è una prova vocale.'),'ja':('Японский','こんにちは。これは音声のテストです。'),
'ka':('Грузинский','გამარჯობა. ეს ხმის ტესტია.'),'kk':('Казахский','Сәлеметсіз бе. Бұл дауыс сынағы.'),
'ko':('Корейский','안녕하세요. 음성 테스트입니다.'),'ku':('Курдский','Silav. Ev ceribandina deng e.'),
'lb':('Люксембургский','Moien. Dëst ass e Stëmmtest.'),'lt':('Литовский','Sveiki. Tai balso bandymas.'),
'lv':('Латышский','Labdien. Šī ir balss pārbaude.'),'ml':('Малаялам','നമസ്കാരം. ഇത് ഒരു ശബ്ദ പരിശോധനയാണ്.'),
'mr':('Маратхи','नमस्कार. ही आवाजाची चाचणी आहे.'),'ne':('Непальский','नमस्ते। यो आवाजको परीक्षण हो।'),
'nl':('Нидерландский','Hallo. Dit is een stemtest.'),'no':('Норвежский','Hei. Dette er en stemmetest.'),
'pl':('Польский','Cześć. To jest próba głosu.'),'pt':('Португальский','Olá. Este é um teste de voz.'),
'ro':('Румынский','Salut. Acesta este un test vocal.'),'ru':('Русский','Привет. Это проверка голоса.'),
'sk':('Словацкий','Dobrý deň. Toto je skúška hlasu.'),'sl':('Словенский','Pozdravljeni. To je preizkus glasu.'),
'sq':('Албанский','Përshëndetje. Ky është një test zëri.'),'sr':('Сербский','Здраво. Ово је провера гласа.'),
'sv':('Шведский','Hej. Det här är ett rösttest.'),'sw':('Суахили','Habari. Hili ni jaribio la sauti.'),
'te':('Телугу','నమస్కారం. ఇది స్వర పరీక్ష.'),'th':('Тайский','สวัสดี นี่คือการทดสอบเสียง'),
'tr':('Турецкий','Merhaba. Bu bir ses denemesidir.'),'uk':('Украинский','Привіт! Це перевірка голосу.'),
'ur':('Урду','سلام۔ یہ آواز کی آزمائش ہے۔'),'vi':('Вьетнамский','Xin chào. Đây là bài kiểm tra giọng nói.'),
'zh':('Китайский','你好。这是语音测试。')}


def main():
    metadata=json.loads(Path('build/library-voice-metadata.json').read_text(encoding='utf-8'))
    library={voice['language']['family']:voice['language']['name_english'] for voice in metadata.values()}
    if set(library)!=set(DATA):raise ValueError('Review library language changes')
    unsupported={'cy','eu','is','ku','lb','ml','sq','sw'}
    result={code:{'name':library[code],'label':DATA[code][0],'sample':DATA[code][1],
                  'stt':code not in unsupported} for code in sorted(library)}
    encoded=json.dumps(result,ensure_ascii=False,indent=2)
    Path('local_component/call_translator_local/languages.json').write_text(encoded+'\n',encoding='utf-8')
    Path('extension/language-library.js').write_text("'use strict';\nglobalThis.CTLanguageLibrary="+encoded+';\n',encoding='utf-8')
    print(json.dumps({'library_languages':len(result),'stt_configured':sum(item['stt'] for item in result.values())}))


if __name__=='__main__':main()
