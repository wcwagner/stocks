$(function () {
    /**
     * Create the chart when all data is loaded
     * @returns {undefined}
     */
     var seriesOptions = [], seriesCounter = 0;

    function createChart() {
        Highcharts.stockChart('stockchart', {

            rangeSelector: {
                selected: 4
            },

            yAxis: {
                labels: {
                    formatter: function () {
                        return (this.value > 0 ? ' + ' : '') + this.value + '%';
                    }
                },
                plotLines: [{
                    value: 0,
                    width: 2,
                    color: 'silver'
                }]
            },

            plotOptions: {
                series: {
                    compare: 'percent',
                    showInNavigator: true
                }
            },

            tooltip: {
                pointFormat: '<span style="color:{series.color}">{series.name}</span>: <b>{point.y}</b> ({point.change}%)<br/>',
                valueDecimals: 2,
                split: true
            },

            series: seriesOptions
        });
    }

    for( var ticker in dailyPrices ){
        seriesOptions[seriesCounter] = {
            name: ticker,
            data: dailyPrices[ticker]
        }
        seriesCounter += 1;
    }
    createChart()
});
