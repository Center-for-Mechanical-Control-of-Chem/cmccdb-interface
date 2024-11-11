import flask
import sys
import traceback

def make_error_response(error, error_code=406):
    tb = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
    print(tb, file=sys.stderr, flush=True)
    return flask.make_response(
        flask.jsonify({
            "type": type(error).__name__,
            "message": str(error),
            "traceback": tb
        }),
        error_code
    )

def make_string_response(str):
    return flask.jsonify({
            "response": str
        })