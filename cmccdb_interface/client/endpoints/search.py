import flask
import requests
import importlib
import json
from psycopg2 import sql


def render_results(result_json:'str|dict'):
    if isinstance(result_json, str):
        result_json = json.loads(result_json)
    flask.session['cached_search_results'] = result_json
    return flask.redirect('/display-results')

def cached_search_results():
    import cmccdb_interface.database.query as query
    # try:
    res = flask.session['cached_search_results']
    # except KeyError:
    #     res = []
    # finally:
    #     try:
    #         del flask.session['cached_search_results']
    #     except:
    #         pass
    return flask.jsonify(res)

def test_query():
    import cmccdb_schema.dataset_constructor as dscon
    importlib.reload(dscon)
    import cmccdb_interface.database.query as query
    query = importlib.reload(query)

    # res = query.get_table_columns("reaction_conditions")
    # return res

    # res = query.get_table_columns("percentage")
    # return res

    # q = query.AdvancedSearchQuery.from_json(
    #     {"DatasetID": f"any of [cmcc_dataset-6510d6e58ec54b6994bfada3be6807b0, cmcc_dataset-6510d]"}
    # )

    q = query.AdvancedSearchQuery.from_json(
        {
            # "WorkupsList":[{"Type":{"allowedValues":2}}],
            "Conditions":{"Mechanochemistry":{"Type":{"allowedValues":3}}}
        }
    )

    q = query.AdvancedSearchQuery.from_json(
        {
            "Conditions": {"Mechanochemistry": {"Type": {"allowedValues": 3}}},
            "OutcomesList": [
                {"ProductsList": [
                    {"MeasurementsList": [
                        {
                            "Type": {"allowedValues": 3},
                            "Percentage": {"Value": ">70"}
                        }
                    ]}
                ]}
            ]}
    )


    # return {"wat":q}

    # q = query.DatasetIdQuery(datasets)

    # return f"""<pre>{q.prep_query()['query']}\n{q.prep_query()['args']}</pre>"""

    res = query.run_query(q, format_results=True)
    return render_results(query.prep_results_for_json(res))

    # flask.session['cached_search_results'] = query.prep_results_for_json(res)
    # return flask.redirect('/display-results')
