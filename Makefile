.PHONY: test test-v apk apk-clean apk-distclean help

help:
	@echo "Target disponibili:"
	@echo "  make test       - lancia tutti i test"
	@echo "  make test-v     - test con output dettagliato"
	@echo "  make apk        - build APK Android (Docker kivy/buildozer)"
	@echo "  make apk-clean  - svuota la cache di build del progetto (.buildozer/)"
	@echo "  make apk-distclean - svuota anche la cache SDK/NDK (.buildozer-global/)"

test:
	python -m unittest discover -s tests

test-v:
	python -m unittest discover -s tests -v

# Build dell'APK di debug via container Docker (niente dipendenze da installare).
# 'yes |' + '-i' accettano automaticamente le licenze SDK (altrimenti aidl non trovato).
# Si montano DUE volumi:
#   - il progetto in /home/user/hostcwd (build, dist, APK in bin/);
#   - .buildozer-global in /home/user/.buildozer = cache di SDK/NDK/ANT, che il
#     container scarica nella propria home: senza questo mount, con --rm verrebbe
#     ributtata a ogni run (ri-download dell'SDK e installazione piattaforma
#     instabile → "Available Android APIs are ()"). Così si scarica una volta sola.
# L'APK risultante finisce in bin/.
apk:
	@mkdir -p .buildozer-global
	@# Auto-cura: se lo state dice "SDK installato" ma nella cache globale il
	@# platform Android non c'è davvero (es. build precedente senza il mount
	@# .buildozer-global), buildozer salterebbe l'installazione → "Available
	@# Android APIs are ()". Azzeriamo la chiave per forzare la reinstallazione.
	@if [ -f .buildozer/state.db ] && ! ls .buildozer-global/android/platform/android-sdk/platforms/android-* >/dev/null 2>&1; then \
		python3 -c "import json; p='.buildozer/state.db'; d=json.load(open(p)); d.pop('android:sdk_installation', None); json.dump(d, open(p,'w'))" 2>/dev/null || true; \
	fi
	yes | docker run --rm -i \
	  -v "$(CURDIR)":/home/user/hostcwd \
	  -v "$(CURDIR)/.buildozer-global":/home/user/.buildozer \
	  kivy/buildozer -v android debug

# Svuota la cache di build del progetto (ricompila l'app; tiene SDK/NDK in cache).
apk-clean:
	rm -rf .buildozer

# Svuota ANCHE la cache globale SDK/NDK (~1.5 GB): il prossimo build riscarica tutto.
apk-distclean:
	rm -rf .buildozer .buildozer-global
