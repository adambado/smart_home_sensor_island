smart_home_site = """
<!DOCTYPE html>
<html>
<html lang="hu">

<head>
    <title>Smart Home</title>
    <style>
        html {
            font-family: 'Arial', 'Arial', Arial, sans-serif;
            display: inline-block;
            margin: 0px auto;
            text-align: center;
        }

        h1 {
            color: #0F3376;
            padding: 2vh;
        }

        p {
            font-size: 1.5rem;
        }
    </style>
    <script>
        var ajaxRequest = new XMLHttpRequest();
        function ajaxLoad(ajaxURL) {
            ajaxRequest.open('GET', ajaxURL, true);
            ajaxRequest.onreadystatechange = function () {
                if (ajaxRequest.readyState == 4 && ajaxRequest.status == 200) {
                    var ajaxResult = ajaxRequest.responseText;
                    var tmpArray = ajaxResult.split("|");
                    document.getElementById('date').innerHTML = tmpArray[0];
                    document.getElementById('temperature').innerHTML = tmpArray[1];
                    document.getElementById('humidity').innerHTML = tmpArray[2];
                    document.getElementById('voltage').innerHTML = tmpArray[3];
                    document.getElementById('luminosity').innerHTML = tmpArray[4];
                    document.getElementById('movement').innerHTML = tmpArray[5];
                    document.getElementById('mode').innerHTML = tmpArray[6];
                }
            }
            ajaxRequest.send();
        } function UpdateSensorData() { ajaxLoad('getSensorData'); }
        setInterval(UpdateSensorData, 1000);
    </script>

<body>
    <h1>Smart Home Web Server</h1>
    <p>Datum es ido: <span id='date'></span><strong></strong></p>
    <p>Homerseklet: <span id='temperature'></span><strong></strong></p>
    <p>Paratartalom: <span id='humidity'></span><strong></strong></p>
    <p>Tapfeszultseg: <span id='voltage'></span><strong></strong></p>
    <p>Fenyero: <span id='luminosity'></span><strong></strong></p>
    <p>Mozgaserzekelo: <span id='movement'></span><strong></strong></p>
    <p>Mod: <span id='mode'></span><strong></strong></p>
</body>
</head>

</html>
"""
