import importlib, inspect
try:
    genai = importlib.import_module('google.generativeai')
    print('module:', genai)
    attrs = [a for a in dir(genai) if not a.startswith('_')]
    print('attrs count:', len(attrs))
    print(attrs)
    if hasattr(genai, 'configure'):
        print('has configure')
    names = [a for a in attrs if 'generate' in a.lower() or 'response' in a.lower() or 'text' in a.lower()]
    print('generate-like names:', names)
    for name in names:
        obj = getattr(genai, name)
        print('\n---', name, '--- type:', type(obj))
        try:
            src = inspect.getsource(obj)
            print(src[:1000])
        except Exception as e:
            print('no source for', name, e)
except Exception as e:
    import traceback; traceback.print_exc()
