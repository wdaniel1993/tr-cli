from tr_cli.delta import decode_delta, decode_response, parse_frame


def test_parse_frame():
    assert parse_frame('12 A {"x":1}') == ("12", "A", '{"x":1}')
    assert parse_frame("3 D  +abc") == ("3", "D", "+abc")
    assert parse_frame("7 C ") == ("7", "C", "")


def test_decode_delta_ops():
    # + appends url-decoded; -N skips N of previous; =N copies N of previous.
    prev = "abcdefghij"
    assert decode_delta(prev, "+XYZ\t-3\t=4\t+123") == "XYZdefg123"


def test_decode_delta_plus_is_url_decoded():
    prev = ""
    assert decode_delta(prev, "+%7B%22a%22%3A1%7D") == '{"a":1}'


def test_decode_response_full():
    sid, code, payload = decode_response('5 A {"type":"cash","total":"1"}')
    assert sid == "5" and code == "A" and payload == {"type": "cash", "total": "1"}


def test_decode_response_delta_keeps_previous():
    prev: dict[str, str] = {}
    decode_response('5 A {"a":1,"b":2}', prev)
    _sid, code, payload = decode_response('5 D +{"a":1,"b":3}', prev)
    assert code == "D" and payload == {"a": 1, "b": 3}
    assert prev["5"] == '{"a":1,"b":3}'


def test_decode_response_close_and_error():
    _sid, code, payload = decode_response("9 C ")
    assert code == "C"
    _sid, code, payload = decode_response("9 E oops")
    assert code == "E" and payload == "oops"
