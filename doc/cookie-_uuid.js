t.prototype.generateUUId = function() {
    var t = (0,
    u.getCookie)("_uuid");
    t && -1 !== t.indexOf("infoc") || (0,
    u.setCookie)("_uuid", (0,
    i.generateUuid)(), 31536e3, "same-domain")
}

e.generateUuid = function() {
    return r(8) + "-" + r(4) + "-" + r(4) + "-" + r(4) + "-" + r(12) + o(String(Date.now() % 1e5), 5) + "infoc"
}


var r = function(t) {
    for (var e = "", n = 0; n < t; n++)
        e += i(16 * Math.random());
    return o(e, t)
};