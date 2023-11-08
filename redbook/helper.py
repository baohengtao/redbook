import json

import execjs


def convert_js_dict_to_py(js_dict: str) -> dict:
    """
    convert a JavaScript dictionary to a Python dictionary
    """
    js_code = f"var dict = {js_dict}; JSON.stringify(dict);"
    ctx = execjs.compile("""
        function convertJsToPy(jsCode) {
            var dict = eval(jsCode);
            return dict;
        }
    """)
    try:
        py_dict = json.loads(ctx.call("convertJsToPy", js_code))
        return py_dict
    except Exception as e:
        print("Error converting JavaScript dictionary to Python:", str(e))
        raise
