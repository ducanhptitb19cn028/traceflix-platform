package com.vinsguru.gateway.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.vinsguru.gateway.client.MovieClient;
import com.vinsguru.gateway.client.SearchClient;
import com.vinsguru.gateway.client.UserClient;
import com.vinsguru.gateway.dto.HomePageDto;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class GatewayServiceTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Mock
    private MovieClient movieClient;
    @Mock
    private UserClient userClient;
    @Mock
    private SearchClient searchClient;

    @InjectMocks
    private GatewayService service;

    private static JsonNode node(String json) {
        try {
            return MAPPER.readTree(json);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    @Test
    void browse_aggregatesUserTrendingAndFeatured() {
        var userNode = node("{\"id\":2,\"name\":\"Bob\"}");
        var trendingNode = node("[{\"id\":1,\"name\":\"The Matrix\"}]");
        var featuredNode = node("{\"id\":1,\"title\":\"The Shawshank Redemption\"}");
        when(userClient.getUser(2)).thenReturn(userNode);
        when(searchClient.search("the")).thenReturn(trendingNode);
        when(movieClient.getMovie(1)).thenReturn(featuredNode);

        HomePageDto home = service.browse(2);

        assertThat(home.userId()).isEqualTo(2);
        assertThat(home.user()).isEqualTo(userNode);
        assertThat(home.trending()).isEqualTo(trendingNode);
        assertThat(home.featured()).isEqualTo(featuredNode);
    }

    @Test
    void browse_fansOutToTheExpectedEndpoints() {
        when(userClient.getUser(5)).thenReturn(node("{}"));
        when(searchClient.search("the")).thenReturn(node("[]"));
        when(movieClient.getMovie(1)).thenReturn(node("{}"));

        service.browse(5);

        verify(userClient).getUser(5);          // gateway -> user
        verify(searchClient).search("the");     // gateway -> search
        verify(movieClient).getMovie(1);        // gateway -> movie (featured)
    }

}
