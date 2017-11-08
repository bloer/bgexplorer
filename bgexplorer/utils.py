from flask import current_app


def get_simsdb():
    """Get the simulations database object"""
    if not current_app:
        return None
    return current_app.extensions.get('SimulationsDB', None)
