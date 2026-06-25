package com.vinsguru.gateway.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.vinsguru.gateway.dto.HomePageDto;
import com.vinsguru.gateway.service.GatewayService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(GatewayController.class)
class GatewayControllerTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private GatewayService gatewayService;

    @Test
    void browse_returnsAggregatedHomePage() throws Exception {
        var home = new HomePageDto(
                2,
                MAPPER.readTree("{\"id\":2,\"name\":\"Bob\",\"role\":\"STANDARD\"}"),
                MAPPER.readTree("[{\"id\":8,\"name\":\"The Matrix\"}]"),
                MAPPER.readTree("{\"id\":1,\"title\":\"The Shawshank Redemption\"}"));
        when(gatewayService.browse(2)).thenReturn(home);

        mockMvc.perform(get("/api/browse").param("userId", "2"))
               .andExpect(status().isOk())
               .andExpect(jsonPath("$.userId").value(2))
               .andExpect(jsonPath("$.user.role").value("STANDARD"))
               .andExpect(jsonPath("$.trending[0].name").value("The Matrix"))
               .andExpect(jsonPath("$.featured.title").value("The Shawshank Redemption"));
    }

}
