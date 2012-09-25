(function($) {
    $.fn.hnh_player = function(player_id) {
        var self = this;
        if (player_id) {
            var url = 'api/status/facebook/' + player_id;
            $.get(url,null,function(data){self.html(data)});
        } else {
            self.html('');
        }
    };
})(jQuery);
