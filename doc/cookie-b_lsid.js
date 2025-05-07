t.prototype.generate = function () {
    var t = (0, u.splitDate)(), e = (0, o.numToHex)(t.millisecond), n = (0, o.randomHex)(8) + "_" + e;
    this.lsid = n,
        this.time.start = t.millisecond,
        this.time.day = t.day,
        (0, u.setCookie)("b_lsid", n, 0, "same-domain")
}

e.randomHex = e.numToHex = e.generateUuid = e.formatNumStr = void 0,

e.generateUuid = function () {
    return r(8) + "-" + r(4) + "-" + r(4) + "-" + r(4) + "-" + r(12) + o(String(Date.now() % 1e5), 5) + "infoc"
}

var r = function(t) {
    for (var e = "", n = 0; n < t; n++)
        e += i(16 * Math.random());
    return o(e, t)
};
e.randomHex = r;


var o = function(t, e) {
    var n = "";
    if (t.length < e)
        for (var r = 0; r < e - t.length; r++)
            n += "0";
    return n + t
};
e.formatNumStr = o;


var i = function(t) {
    return Math.ceil(t).toString(16).toUpperCase()
};
e.numToHex = i