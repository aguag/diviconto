.PHONY: test test-v apk apk-clean help

help:
	@echo "Target disponibili:"
	@echo "  make test       - lancia tutti i test"
	@echo "  make test-v     - test con output dettagliato"
	@echo "  make apk        - build APK Android (Docker kivy/buildozer)"
	@echo "  make apk-clean  - svuota la cache di build (.buildozer/)"

test:
	python -m unittest discover -s tests

test-v:
	python -m unittest discover -s tests -v

# Build dell'APK di debug via container Docker (niente dipendenze da installare).
# 'yes |' + '-i' accettano automaticamente le licenze SDK (altrimenti aidl non trovato).
# L'APK risultante finisce in bin/.
apk:
	yes | docker run --rm -i -v "$(CURDIR)":/home/user/hostcwd kivy/buildozer -v android debug

# Rimuove la cache SDK/NDK/build per un build pulito (riscaricherà tutto).
apk-clean:
	rm -rf .buildozer
