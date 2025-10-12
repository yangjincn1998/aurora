from services.web_request.web_service import WebService

class JavBusWebService(WebService):
    def __init__(self):
        self._url = "https://www.javbus.com/"
        self._available = True

    def url(self):
        return self._url
    def available(self):
        return self._available