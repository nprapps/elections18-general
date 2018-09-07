var $acceptAP;
var $rejectAP;
var $callNPR;
var $uncallNPR;
var $overlay;
var $body;
var $allowChamberCall;
var $callChamberDem;
var $callChamberGOP;
var $uncallChamber;

var ACCEPT_AP_URL = document.location.href + 'accept-ap';
var CALL_NPR_URL = document.location.href + 'call-npr';
var CHAMBER_CALL_URL = document.location.href + 'call-chamber';

var pageRefresh = null;

var onDocumentLoad = function() {
    $acceptAP = $('.accept-ap');
    $rejectAP = $('.reject-ap')
    $callNPR = $('.npr-call');
    $uncallNPR = $('.npr-uncall');
    $overlay = $('.overlay');
    $body = $('body');

    $acceptAP.on('click', onAPClick);
    $rejectAP.on('click', onAPClick);
    $callNPR.on('click', onCallNPRClick);
    $uncallNPR.on('click', onUncallNPRClick);

    $allowChamberCall = $('#allow-chamber-call');
    $callChamberDem = $('#call-chamber-dem');
    $callChamberGOP = $('#call-chamber-gop');
    $uncallChamber = $('#uncall-chamber');
    if ($allowChamberCall) { $allowChamberCall.on('click', onAllowChamberCall); }
    if ($callChamberDem) { $callChamberDem.on('click', onCallChamberDem); }
    if ($callChamberGOP) { $callChamberGOP.on('click', onCallChamberGOP); }
    if ($uncallChamber) { $uncallChamber.on('click', onUncallChamber); }

    pageRefresh = setInterval(refreshPage, 10000);
}

var onAPClick = function(e) {
    var reportingunit = $(this).data('reportingunit') !== 'None' ? $(this).data('reportingunit') : ''

    console.log(reportingunit);
    var data = {
        race_id: $(this).data('race-id'),
        statepostal: $(this).data('statepostal'),
        reportingunit: reportingunit,
        level: $(this).data('level')
    }

    $overlay.fadeIn();
    $.post(ACCEPT_AP_URL, data,function() {
        refreshPage(true);
    });
}

var onCallNPRClick = function(e) {
    var data = {
        race_id: $(this).data('race-id'),
        result_id: $(this).data('result-id')
    }

    $overlay.fadeIn();
    $.post(CALL_NPR_URL, data, function() {
        refreshPage(true);
    });
}

var onUncallNPRClick = function(e) {
    var data = {
        race_id: $(this).data('race-id'),
        result_id: $(this).data('result-id')
    }

    $overlay.fadeIn();
    $.post(CALL_NPR_URL, data, function() {
        refreshPage(true);
    });
}

var onAllowChamberCall = function(e) {
    $allowChamberCall.addClass('hidden');
    $callChamberDem.removeClass('hidden');
    $callChamberGOP.removeClass('hidden');
}

var callChamber = function(party) {
    var data = { call: party };

    $overlay.fadeIn();
    $.post(CHAMBER_CALL_URL, data, function() {
        refreshPage(true);
    });
}

var onUncallChamber = function(e) { callChamber(null); }
var onCallChamberDem = function(e) { callChamber('Dem'); }
var onCallChamberGOP = function(e) { callChamber('GOP'); }

var refreshPage = function() {
    $.get(window.location.href, function(data) {
        var $oldContainer = $('.container');
        var $newHTML = $(data);
        var $newContainer = $newHTML.filter('.container');
        $oldContainer.html($newContainer);

        $acceptAP.off('click');
        $rejectAP.off('click');
        $callNPR.off('click');
        $uncallNPR.off('click');
        clearInterval(pageRefresh);

        onDocumentLoad();

        $overlay.fadeOut();
    });
}

$(onDocumentLoad);
